"""LangGraph node implementations for the agent pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ._prompts import _ROUTER_PROMPT, _SKILL_MAP, _SYSTEM_PROMPT_BASE
from ._state import AgentState  # noqa: TC001

logger = logging.getLogger("aquila.reasoning")


if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService

    from ._state import _RouteType

# Tool results larger than this are truncated before being sent to the LLM.
# This prevents the synthesis call from overflowing the model's context window
# when tools like repo_overview or module_map return large payloads.
_MAX_TOOL_RESULT_CHARS = 12_000


def _msg_text(content: Any) -> str:
    """Extract plain text from an LLM message content field.

    Handles both plain strings and the list-of-blocks format used by some
    OpenAI-compatible providers: ``[{"type": "text", "text": "..."}]``.
    Falls back to any dict with a "text" key when no standard "text" block is
    present (covers providers that use "output_text", "answer", etc.).
    """
    if isinstance(content, list):
        typed = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
        if typed:
            return typed
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content) if content else ""


def _cap_tool_messages(messages: list[Any]) -> list[Any]:
    """Truncate each ToolMessage to _MAX_TOOL_RESULT_CHARS.

    Tool results (repo_overview, module_map, semantic_search, …) can be very
    large.  Sending them verbatim pushes the synthesis call over the model's
    context ceiling, causing it to return an empty response.  Capping each
    result to a fixed size keeps total context predictable without losing the
    essential information.
    """
    from langchain_core.messages import ToolMessage  # noqa: PLC0415

    out: list[Any] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            text = _msg_text(getattr(m, "content", ""))
            if len(text) > _MAX_TOOL_RESULT_CHARS:
                trimmed = text[:_MAX_TOOL_RESULT_CHARS] + "\n…[truncated]"
                logger.debug(
                    "agent[reasoning] capped tool result %d→%d chars tool_call_id=%s",
                    len(text),
                    len(trimmed),
                    getattr(m, "tool_call_id", "?"),
                )
                m = ToolMessage(content=trimmed, tool_call_id=m.tool_call_id)
        out.append(m)
    return out


def _router_node(state: AgentState, llm: Any) -> dict[str, Any]:
    """Classify the query as 'retrieval' or 'direct'."""
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if last_human is None:
        return {"route": "direct"}

    query = str(last_human.content)

    # Include the last 2 turns of conversation so the router can classify
    # follow-up questions correctly (e.g. "are they all python files?" after
    # "how many files?" needs the prior context to route as "structural").
    prior = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage))]
    prior = prior[:-1]  # exclude the current human message
    if prior:
        snippet_lines = []
        for m in prior[-4:]:  # at most 2 prior turns
            role = "User" if isinstance(m, HumanMessage) else "AI"
            text = _msg_text(m.content)[:300].replace("\n", " ")
            snippet_lines.append(f"  {role}: {text}")
        context_block = (
            "Recent conversation (for context only):\n" + "\n".join(snippet_lines) + "\n\n"
        )
    else:
        context_block = ""

    logger.info("agent[router] query=%r prior_turns=%d", query, len(prior))
    response = llm.invoke(
        [HumanMessage(content=_ROUTER_PROMPT.format(context_block=context_block, query=query))],
    )
    text = str(response.content).strip().lower()
    if "direct" in text:
        route: _RouteType = "direct"
    elif "diagram" in text:
        route = "diagram"
    elif "structural" in text:
        route = "structural"
    elif "generation" in text:
        route = "generation"
    elif "analysis" in text:
        route = "analysis"
    else:
        route = "implementation"
    logger.info("agent[router] → route=%s", route)
    return {"route": route}


def _retrieval_node(state: AgentState, service: KnowledgeService) -> dict[str, Any]:
    """Fetch relevant code chunks from the vector store."""
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    query = str(last_human.content) if last_human else ""
    repo_id = state["repo_id"]
    route = state.get("route", "implementation")

    # For structural/overview questions the user query is vague ("what does this do?").
    # Augment it so the vector search returns representative entry-point chunks.
    if route == "structural":
        search_query = f"main module entry point overview architecture {query}"
        top_k = 6
    elif route == "diagram":
        # Broad structural sweep: entry points, key classes, key files
        search_query = f"module class file structure entry point overview {query}"
        top_k = 5
    elif route == "generation":
        search_query = query
        top_k = 5
    elif route == "analysis":
        search_query = f"suggestion design formula quality computation {query}"
        top_k = 4
    else:
        search_query = query
        top_k = 4

    logger.info("agent[retrieval] repo=%s route=%s query=%r", repo_id, route, search_query)

    results = service.search(query=search_query, repo_id=repo_id, top_k=top_k)
    if not results:
        logger.info("agent[retrieval] → 0 chunks found")
        return {"retrieved_context": "No relevant code found in the repository."}

    logger.info("agent[retrieval] → %d chunks found", len(results))
    parts = [
        f"# {r.file_path}:{r.start_line}-{r.end_line} [{r.chunk_type}] "
        f"score={r.score:.4f}\n{r.content}"
        for r in results
    ]
    return {"retrieved_context": "\n\n---\n\n".join(parts)}


async def _reasoning_node(state: AgentState, llm: Any) -> dict[str, Any]:
    """Generate the assistant response, incorporating any retrieved context.

    Async so that LangGraph's ``astream_events`` can properly emit
    ``on_chat_model_stream`` events for each token — sync nodes run in a
    thread executor where the LangChain callback bridge is unreliable.
    """
    from langchain_core.messages import ToolMessage  # noqa: PLC0415

    context = state.get("retrieved_context", "")
    route = state.get("route", "implementation")
    repo_id = state["repo_id"]
    skill = _SKILL_MAP.get(route, "")
    logger.info(
        "agent[reasoning] route=%s skill=%s context_len=%d",
        route,
        bool(skill),
        len(context),
    )
    system_content = _SYSTEM_PROMPT_BASE
    # Explicitly pin the repo_id so the LLM never guesses "repo" or another placeholder.
    system_content += (
        f"\n\n## Active repository\n"
        f"repo_id: `{repo_id}` — pass this exact string as the `repo_id` parameter "
        f"in **every** tool call, without exception."
    )
    if skill:
        system_content += f"\n\n{skill}"
    if context:
        system_content += f"\n\nRetrieved context from codebase:\n\n{context}"

    # Guard against infinite tool-call loops: count only the ToolMessages added
    # *after* the last HumanMessage (i.e. the current turn's tool calls only).
    messages_list = state["messages"]
    last_human_idx = next(
        (i for i, m in reversed(list(enumerate(messages_list))) if isinstance(m, HumanMessage)),
        0,
    )
    tool_call_count = sum(1 for m in messages_list[last_human_idx:] if isinstance(m, ToolMessage))
    if tool_call_count >= 5:
        logger.warning(
            "agent[reasoning] %d tool calls detected — injecting stop-loop instruction",
            tool_call_count,
        )
        system_content += (
            "\n\n**IMPORTANT**: You have already called tools multiple times. "
            "Do NOT call any more tools. Using the tool results already in this conversation, "
            "write a complete, final answer for the user right now."
        )

    # Cap individual tool results to prevent the synthesis call from overflowing
    # the model's context window when tools return large payloads.
    messages: list[Any] = [
        SystemMessage(content=system_content),
        *_cap_tool_messages(messages_list),
    ]
    logger.debug(
        "agent[reasoning] prompt messages=%d system_len=%d tool_calls_so_far=%d",
        len(messages),
        len(system_content),
        tool_call_count,
    )

    response = await llm.ainvoke(messages)
    response_text = _msg_text(getattr(response, "content", ""))
    tool_calls = getattr(response, "tool_calls", None)
    logger.debug(
        "agent[reasoning] response content_len=%d tool_calls=%r response_type=%s",
        len(response_text),
        tool_calls,
        type(response).__name__,
    )

    # Recovery: if the LLM returned empty content with no valid tool calls, force a
    # synthesis pass so the user never receives a blank response.
    if not response_text and not tool_calls:
        has_tool_results = tool_call_count > 0
        recovery_content = (
            "Using the tool results already in this conversation, "
            "write a complete answer for the user. Do not call any more tools."
            if has_tool_results
            else (
                "Your last response was empty. "
                "Please provide a complete, helpful answer to the user's question "
                "based on the context provided. Do not call any tools."
            )
        )
        logger.warning(
            "agent[reasoning] empty response finish_reason=%s — recovery pass (has_tool_results=%s)",
            (getattr(response, "response_metadata", {}) or {}).get("finish_reason"),
            has_tool_results,
        )
        recovery = await llm.ainvoke(messages + [HumanMessage(content=recovery_content)])
        if _msg_text(getattr(recovery, "content", "")):
            response = recovery

    return {"messages": [response]}


def _route_condition(state: AgentState) -> str:
    return state.get("route", "implementation")
