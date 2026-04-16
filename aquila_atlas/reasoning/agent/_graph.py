"""build_graph — compile the LangGraph state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph

    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService


def build_graph(
    service: KnowledgeService,
    settings: Settings,
    extra_tools: list[BaseTool] | None = None,
) -> CompiledStateGraph[Any]:
    """Compile the LangGraph state machine.

    Args:
        service: Initialised knowledge service.
        settings: Application settings (LLM config).
        extra_tools: Additional LangChain tools to bind to the LLM (e.g. MCP tools).
            Combined with the built-in knowledge tools from
            :func:`~aquila_atlas.reasoning.tools.get_tools`.

    Returns:
        Compiled LangGraph ready for ``invoke`` / ``stream`` / ``ainvoke`` / ``astream``.
    """
    from langchain_openai import ChatOpenAI  # noqa: PLC0415
    from langgraph.graph import START, StateGraph  # noqa: PLC0415
    from langgraph.prebuilt import ToolNode, tools_condition  # noqa: PLC0415

    from aquila_atlas.reasoning.tools import get_tools as get_knowledge_tools  # noqa: PLC0415

    from ._nodes import _reasoning_node, _retrieval_node, _route_condition, _router_node
    from ._state import AgentState

    llm = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        streaming=True,
        stream_usage=True,  # include usage metadata in the final streaming chunk
    )

    all_tools = get_knowledge_tools(service, settings) + (extra_tools or [])
    llm_with_tools = llm.bind_tools(all_tools)

    def router_node(state: AgentState) -> dict[str, Any]:
        return _router_node(state, llm)

    def retrieval_node(state: AgentState) -> dict[str, Any]:
        return _retrieval_node(state, service)

    async def reasoning_node(state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage, ToolMessage  # noqa: PLC0415

        # Count only current-turn tool calls (after the last HumanMessage) so that
        # ToolMessages from previous session turns don't inflate the count.
        messages_list = state["messages"]
        last_human_idx = next(
            (
                i
                for i, m in reversed(list(enumerate(messages_list)))
                if isinstance(m, HumanMessage)
            ),
            0,
        )
        tool_call_count = sum(
            1 for m in messages_list[last_human_idx:] if isinstance(m, ToolMessage)
        )
        # Hard-stop: after 5 tool results, switch to bare LLM so tools_condition
        # sees no tool_calls and exits the graph immediately.  This prevents the
        # recursion limit from being reached on broad structural questions.
        if state.get("route") == "direct" or tool_call_count >= 5:
            active_llm = llm
        else:
            active_llm = llm_with_tools
        return await _reasoning_node(state, active_llm)

    builder: StateGraph[AgentState] = StateGraph(AgentState)
    builder.add_node("router", router_node)
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("reasoning", reasoning_node)
    builder.add_node("tools", ToolNode(all_tools, handle_tool_errors=True))

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        _route_condition,
        {
            "implementation": "retrieval",  # pre-fetch vector context first
            "structural": "retrieval",  # broad retrieval + graph tools as supplement
            "analysis": "retrieval",  # fetch code with formulas first
            "generation": "retrieval",  # fetch the code to document first
            "diagram": "retrieval",  # light structural context before generate_mermaid
            "direct": "reasoning",  # no retrieval needed
        },
    )
    builder.add_edge("retrieval", "reasoning")
    builder.add_conditional_edges("reasoning", tools_condition)
    builder.add_edge("tools", "reasoning")

    return builder.compile()
