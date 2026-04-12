"""LangGraph agent for Aquila-Atlas codebase Q&A.

Implements a router → retrieval → reasoning pipeline with conversation memory
and optional LangSmith tracing.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages

_RouteType = Literal["structural", "implementation", "analysis", "generation", "diagram", "direct"]

logger = logging.getLogger("aquila.reasoning")

# ---------------------------------------------------------------------------
# Streaming event types
# ---------------------------------------------------------------------------


class AgentStreamEvent(TypedDict, total=False):
    """Discriminated event emitted by :meth:`CodebaseAgent.astream_with_status`.

    Exactly one of ``token`` or ``status`` is set per event.
    """

    token: str
    status: str
    input_tokens: int
    output_tokens: int


# Human-readable status labels per LangGraph node and LangChain tool name.
_NODE_STATUS: dict[str, str] = {
    "router": "Classifying query...",
    "retrieval": "Searching codebase...",
    "reasoning": "Thinking...",
    "tools": "Running tools...",
}

_TOOL_STATUS: dict[str, str] = {
    "semantic_search": "Semantic search...",
    "graph_traversal": "Traversing dependency graph...",
    "file_reader": "Reading file...",
    "summarize": "Summarizing...",
    "generate_docstring": "Generating docstring...",
    "generate_mermaid": "Generating diagram...",
    "validate_mermaid": "Validating diagram...",
    "get-schema": "Reading graph schema...",
    "read-cypher": "Querying graph...",
    "write-cypher": "Writing to graph...",
}

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph

    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg_text(content: Any) -> str:
    """Extract plain text from an LLM message content field.

    Handles both plain strings and the list-of-blocks format used by some
    OpenAI-compatible providers: ``[{"type": "text", "text": "..."}]``.
    """
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content) if content else ""


# ---------------------------------------------------------------------------
# Prompt loader — reads .md files from the prompts/ directory next to this file
# ---------------------------------------------------------------------------

_PROMPTS_DIR = __file__.replace("agent.py", "prompts")


def _load_prompt(name: str) -> str:
    """Load a prompt template from ``prompts/<name>.md``.

    Falls back to an empty string if the file is missing so the agent
    degrades gracefully during development (e.g. before prompts are written).
    """
    import pathlib  # noqa: PLC0415

    path = pathlib.Path(_PROMPTS_DIR) / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("prompt file not found: %s", path)
        return ""


# Loaded once at import time — restart the server to pick up edits.
_SYSTEM_PROMPT_BASE = _load_prompt("system_base")
_ROUTER_PROMPT = _load_prompt("router")

_SKILL_MAP: dict[str, str] = {
    "structural": _load_prompt("skill_architecture"),
    "implementation": _load_prompt("skill_implementation"),
    "analysis": _load_prompt("skill_analysis"),
    "generation": _load_prompt("skill_documentation"),
    "diagram": _load_prompt("skill_diagram"),
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """LangGraph state threaded through every node."""

    messages: Annotated[list[BaseMessage], add_messages]
    repo_id: str
    retrieved_context: str
    route: _RouteType


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


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
        top_k = 10
    elif route == "diagram":
        # Broad structural sweep: entry points, key classes, key files
        search_query = f"module class file structure entry point overview {query}"
        top_k = 8
    elif route == "generation":
        search_query = query
        top_k = 8
    elif route == "analysis":
        search_query = f"suggestion design formula quality computation {query}"
        top_k = 6
    else:
        search_query = query
        top_k = 6

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


def _reasoning_node(state: AgentState, llm: Any) -> dict[str, Any]:
    """Generate the assistant response, incorporating any retrieved context."""
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

    # Guard against infinite tool-call loops: if 5+ tool results already exist in this
    # turn, force the LLM to stop calling tools and synthesise a final answer.
    from langchain_core.messages import ToolMessage  # noqa: PLC0415

    tool_call_count = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
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

    messages: list[BaseMessage] = [SystemMessage(content=system_content), *state["messages"]]
    logger.debug(
        "agent[reasoning] prompt messages=%d system_len=%d tool_calls_so_far=%d",
        len(messages),
        len(system_content),
        tool_call_count,
    )

    response = llm.invoke(messages)
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
        if has_tool_results:
            recovery_content = (
                "Your last action produced no output. "
                "Using the tool results already in this conversation, "
                "write a complete answer for the user. "
                "Do not call any more tools."
            )
        else:
            recovery_content = (
                "Your last response was empty. "
                "Please provide a complete, helpful answer to the user's question "
                "based on the context provided. Do not call any tools."
            )
        logger.warning(
            "agent[reasoning] empty response — forcing recovery pass (has_tool_results=%s)",
            has_tool_results,
        )
        recovery = llm.invoke(messages + [HumanMessage(content=recovery_content)])
        if _msg_text(getattr(recovery, "content", "")):
            response = recovery

    return {"messages": [response]}


def _route_condition(state: AgentState) -> str:
    return state.get("route", "implementation")


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


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
    from langgraph.prebuilt import ToolNode, tools_condition  # noqa: PLC0415

    # noqa: PLC0415
    from aquila_atlas.reasoning.tools import get_tools as get_knowledge_tools  # noqa: PLC0415

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

    def reasoning_node(state: AgentState) -> dict[str, Any]:
        return _reasoning_node(state, llm_with_tools)

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


# ---------------------------------------------------------------------------
# CodebaseAgent — stateful multi-turn wrapper
# ---------------------------------------------------------------------------


class CodebaseAgent:
    """Stateful, multi-turn agent for codebase Q&A.

    Maintains conversation history across calls and exposes both a blocking
    :meth:`chat` method and a token-streaming :meth:`stream` generator.

    Example::

        agent = CodebaseAgent(service, repo_id="myrepo")
        print(agent.chat("How does authentication work?"))

        for token in agent.stream("Show me the login function"):
            print(token, end="", flush=True)
    """

    def __init__(
        self,
        service: KnowledgeService,
        repo_id: str,
        settings: Settings | None = None,
        extra_tools: list[BaseTool] | None = None,
    ) -> None:
        from langchain_openai import ChatOpenAI  # noqa: PLC0415

        from aquila_atlas.config import get_settings  # noqa: PLC0415

        s = settings or get_settings()
        _configure_langsmith(s)
        self._graph = build_graph(service, s, extra_tools=extra_tools)
        self._repo_id = repo_id
        self._history: list[BaseMessage] = []
        self._settings = s
        # Lightweight LLM client used only for history compaction (no tools bound).
        self._compaction_llm = ChatOpenAI(
            model=s.llm_model,
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
        )

    # ------------------------------------------------------------------
    # History access (used by the API layer for persistence)
    # ------------------------------------------------------------------

    def get_history(self) -> list[BaseMessage]:
        """Return a snapshot of the current conversation history."""
        return list(self._history)

    def set_history(self, messages: list[BaseMessage]) -> None:
        """Restore conversation history (e.g. after loading from Valkey)."""
        self._history = list(messages)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, query: str) -> str:
        """Send a message and return the complete response (blocking).

        Args:
            query: Natural language question about the codebase.

        Returns:
            Assistant response as a plain string.
        """
        logger.info("CodebaseAgent.chat repo=%s query=%r", self._repo_id, query)
        self._compact_history()
        self._history.append(HumanMessage(content=query))
        result = self._graph.invoke(self._build_input())
        self._history = result["messages"]
        last_ai = next(
            (m for m in reversed(self._history) if isinstance(m, AIMessage)),
            None,
        )
        text = _msg_text(last_ai.content) if last_ai else ""
        if not text:
            logger.warning("agent[chat] empty response, retrying with bare LLM")
            text = self._retry_bare()
        return text

    def stream(self, query: str) -> Iterator[str]:
        """Send a message and stream the response token by token.

        Args:
            query: Natural language question about the codebase.

        Yields:
            Response tokens as they are generated.
        """
        logger.info("CodebaseAgent.stream repo=%s query=%r", self._repo_id, query)
        self._compact_history()
        self._history.append(HumanMessage(content=query))
        accumulated = ""
        for chunk, metadata in self._graph.stream(self._build_input(), stream_mode="messages"):
            if (
                metadata.get("langgraph_node") == "reasoning"
                and isinstance(chunk, AIMessage)
                and chunk.content
            ):
                token = str(chunk.content)
                accumulated += token
                yield token
        if accumulated:
            self._history.append(AIMessage(content=accumulated))
        else:
            if self._history and isinstance(self._history[-1], HumanMessage):
                self._history.pop()
            logger.warning("agent[stream] empty accumulated response for query=%r", query)

    async def astream_with_status(
        self,
        query: str,
        timeout: float = 180.0,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Async streaming with interleaved status events.

        Yields :class:`AgentStreamEvent` dicts — each has either a ``token``
        key (LLM output fragment) or a ``status`` key (human-readable progress
        label such as *"Searching codebase..."*).  Used by the SSE chat
        endpoint so the UI can show the user what the agent is doing instead
        of a blank screen.

        Args:
            query: Natural language question about the codebase.
            timeout: Maximum seconds to wait for the full response (default 180).

        Yields:
            ``{"token": "..."}`` or ``{"status": "..."}`` dicts.
        """
        import asyncio  # noqa: PLC0415

        logger.info("CodebaseAgent.astream_with_status repo=%s query=%r", self._repo_id, query)
        await self._compact_history_async()
        self._history.append(HumanMessage(content=query))
        accumulated = ""
        last_answer_text = ""
        input_tokens = 0
        output_tokens = 0

        config = RunnableConfig(recursion_limit=25)
        timed_out = False
        try:
            async with asyncio.timeout(timeout):
                async for event in self._graph.astream_events(
                    self._build_input(), config, version="v2"
                ):
                    etype = event["event"]
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    name = event.get("name", "")

                    if etype == "on_chain_start":
                        if name in _NODE_STATUS:
                            yield {"status": _NODE_STATUS[name]}

                    elif etype == "on_tool_start":
                        yield {"status": _TOOL_STATUS.get(name, f"Running {name}...")}

                    elif node == "router":
                        continue

                    elif etype in {"on_chat_model_stream", "on_llm_stream"}:
                        chunk = event["data"].get("chunk")
                        text = _msg_text(getattr(chunk, "content", chunk))
                        if text:
                            accumulated += text
                            yield {"token": text}

                    elif etype in {"on_chat_model_end", "on_llm_end"}:
                        output = event["data"].get("output") or event["data"].get("content")
                        if output is not None:
                            # LangChain AIMessage stores usage in usage_metadata
                            # (standard) or response_metadata.token_usage (OpenAI).
                            # Accumulate across all LLM calls in the turn (router +
                            # reasoning + any tool-call reasoning steps).
                            usage_meta = getattr(output, "usage_metadata", None)
                            if isinstance(usage_meta, dict):
                                input_tokens += usage_meta.get("input_tokens", 0)
                                output_tokens += usage_meta.get("output_tokens", 0)
                            else:
                                resp_meta = getattr(output, "response_metadata", {}) or {}
                                tok = (
                                    resp_meta.get("token_usage", {})
                                    if isinstance(resp_meta, dict)
                                    else {}
                                )
                                input_tokens += tok.get("prompt_tokens", 0)
                                output_tokens += tok.get("completion_tokens", 0)

                            text = _msg_text(getattr(output, "content", output))
                            if text:
                                last_answer_text = text

                    elif etype == "on_chain_end" and node == "reasoning":
                        # Reliable fallback: LangGraph always emits on_chain_end with the
                        # node's full output dict, even when on_chat_model_stream events
                        # don't propagate from sync nodes running in a thread pool.
                        output = event["data"].get("output", {})
                        if isinstance(output, dict):
                            msgs = output.get("messages", [])
                            for msg in reversed(msgs):
                                if isinstance(msg, AIMessage):
                                    text = _msg_text(getattr(msg, "content", ""))
                                    if text and not getattr(msg, "tool_calls", None):
                                        last_answer_text = text
                                    break
        except TimeoutError:
            logger.warning("CodebaseAgent.astream_with_status timed out after %.0fs", timeout)
            timed_out = True
            if not accumulated:
                yield {
                    "token": "\n\n_Response timed out. Please try again or rephrase your question._"
                }
                accumulated = "(timed out)"
        except Exception as exc:  # noqa: BLE001
            from langgraph.errors import GraphRecursionError  # noqa: PLC0415

            if isinstance(exc, GraphRecursionError):
                logger.warning("CodebaseAgent.astream_with_status recursion limit reached")
                msg = (
                    last_answer_text
                    or "I reached my tool-call limit before finishing. "
                    "Please try a more specific question."
                )
                if not accumulated:
                    yield {"token": msg}
                    accumulated = msg
                # Don't re-raise — treat as a completed (degraded) response.
            else:
                raise

        if not accumulated and last_answer_text:
            accumulated = last_answer_text
            yield {"token": accumulated}

        # Yield final event with token counts (always, so the frontend can clear
        # the "0 / 0" placeholder even when the model doesn't report usage).
        if not timed_out:
            yield {"input_tokens": input_tokens, "output_tokens": output_tokens}

        if not timed_out:
            if not accumulated:
                logger.warning(
                    "agent[astream_with_status] empty response, retrying with bare LLM query=%r",
                    query,
                )
                accumulated = await self._retry_bare_async()
                if accumulated:
                    yield {"token": accumulated}
            self._history.append(AIMessage(content=accumulated))

    async def achat(self, query: str) -> str:
        """Async version of :meth:`chat` — required when MCP tools are active.

        Args:
            query: Natural language question about the codebase.

        Returns:
            Assistant response as a plain string.
        """
        logger.info("CodebaseAgent.achat repo=%s query=%r", self._repo_id, query)
        await self._compact_history_async()
        self._history.append(HumanMessage(content=query))
        result = await self._graph.ainvoke(self._build_input())
        self._history = result["messages"]
        last_ai = next(
            (m for m in reversed(self._history) if isinstance(m, AIMessage)),
            None,
        )
        text = _msg_text(last_ai.content) if last_ai else ""
        if not text:
            logger.warning("agent[achat] empty response, retrying with bare LLM")
            text = await self._retry_bare_async()
        return text

    async def astream(self, query: str) -> AsyncIterator[str]:
        """Async streaming version of :meth:`stream` — required when MCP tools are active.

        Args:
            query: Natural language question about the codebase.

        Yields:
            Response tokens as they are generated.
        """
        logger.info("CodebaseAgent.astream repo=%s query=%r", self._repo_id, query)
        await self._compact_history_async()
        self._history.append(HumanMessage(content=query))
        accumulated = ""
        # Fallback for non-SSE endpoints: track the last text-bearing LLM
        # response that is *not* a pure tool-dispatch turn.  We update this
        # every time we see such a response so the final answer is always
        # captured even after multiple tool-call iterations.
        last_answer_text = ""

        config = RunnableConfig(recursion_limit=25)
        try:
            async for event in self._graph.astream_events(
                self._build_input(), config, version="v2"
            ):
                etype = event["event"]
                node = event.get("metadata", {}).get("langgraph_node")
                if node == "router":
                    continue

                if etype in {"on_chat_model_stream", "on_llm_stream"}:
                    chunk = event["data"].get("chunk")
                    text = _msg_text(getattr(chunk, "content", chunk))
                    if text:
                        accumulated += text
                        yield text

                elif etype in {"on_chat_model_end", "on_llm_end"}:
                    output = event["data"].get("output") or event["data"].get("content")
                    if output is not None:
                        tool_calls = getattr(output, "tool_calls", [])
                        text = _msg_text(getattr(output, "content", output))
                        if text:
                            if tool_calls:
                                logger.debug(
                                    "agent[reasoning] end event with tool_calls tool_calls=%r",
                                    tool_calls,
                                )
                            last_answer_text = text

                elif etype == "on_chain_end" and node == "reasoning":
                    # Reliable fallback: capture the node output directly, since
                    # on_chat_model_stream events may not propagate from sync nodes.
                    output = event["data"].get("output", {})
                    if isinstance(output, dict):
                        msgs = output.get("messages", [])
                        for msg in reversed(msgs):
                            if isinstance(msg, AIMessage):
                                text = _msg_text(getattr(msg, "content", ""))
                                if text and not getattr(msg, "tool_calls", None):
                                    last_answer_text = text
                                break

                else:
                    data = event.get("data", {})
                    data_keys = list(data.keys()) if isinstance(data, dict) else type(data)
                    logger.debug(
                        "agent[reasoning] event ignored event=%s node=%s data_keys=%s",
                        etype,
                        node,
                        data_keys,
                    )
        except Exception as exc:  # noqa: BLE001
            from langgraph.errors import GraphRecursionError  # noqa: PLC0415

            if isinstance(exc, GraphRecursionError):
                logger.warning("CodebaseAgent.astream recursion limit reached")
                if not accumulated:
                    fallback = (
                        last_answer_text
                        or "I reached my tool-call limit before finishing. "
                        "Please try a more specific question."
                    )
                    accumulated = fallback
                    yield fallback
            else:
                raise

        # Non-streaming / batch endpoints: emit the captured final answer.
        if not accumulated and last_answer_text:
            accumulated = last_answer_text
            yield accumulated

        if not accumulated:
            logger.warning("agent[astream] empty response, retrying with bare LLM query=%r", query)
            accumulated = await self._retry_bare_async()
            if accumulated:
                yield accumulated
        self._history.append(AIMessage(content=accumulated))

    # ------------------------------------------------------------------
    # Bare-LLM retry helpers
    # ------------------------------------------------------------------

    def _retry_bare(self) -> str:
        """Re-invoke the plain LLM (no tools) when the graph returns an empty response.

        ``self._history`` already contains the current HumanMessage, so the
        retry gets full context without any extra setup.
        """
        logger.info("agent[retry] invoking bare LLM for recovery")
        result = self._compaction_llm.invoke(
            [SystemMessage(content=_SYSTEM_PROMPT_BASE), *self._history]
        )
        return _msg_text(result.content)

    async def _retry_bare_async(self) -> str:
        """Async version of :meth:`_retry_bare`."""
        logger.info("agent[retry] invoking bare LLM for recovery (async)")
        result = await self._compaction_llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT_BASE), *self._history]
        )
        return _msg_text(result.content)

    # ------------------------------------------------------------------
    # Compaction helpers
    # ------------------------------------------------------------------

    def _estimate_tokens(self) -> int:
        """Rough token estimate for current history (4 chars ≈ 1 token)."""
        return sum(len(_msg_text(m.content)) for m in self._history) // 4

    def _build_summary_prompt(self, to_summarise: list[BaseMessage]) -> str:
        flat = "\n\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {_msg_text(m.content)}"
            for m in to_summarise
        )
        return (
            "Summarise the following conversation in 4-6 concise bullet points. "
            "Preserve all technical details: file names, function names, decisions made, "
            "and conclusions reached. Do not add anything not in the original.\n\n"
            f"{flat}"
        )

    def _apply_compaction(self, summary: str, keep: int) -> None:
        self._history = [
            HumanMessage(content=f"[Earlier conversation summary]\n{summary}"),
            AIMessage(content="Understood. I'll keep that context in mind."),
            *self._history[-keep:],
        ]
        logger.info("agent[compaction] history compacted to %d messages", len(self._history))

    def _compact_history(self) -> None:
        """Summarise old messages when history exceeds the configured token limit."""
        keep = 4  # always retain the last 2 turns verbatim
        if self._estimate_tokens() <= self._settings.max_history_tokens:
            return
        to_summarise = self._history[:-keep] if len(self._history) > keep else []
        if not to_summarise:
            return
        logger.info(
            "agent[compaction] %d tokens > %d limit, compacting %d messages",
            self._estimate_tokens(),
            self._settings.max_history_tokens,
            len(to_summarise),
        )
        response = self._compaction_llm.invoke(
            [
                SystemMessage(content="You are a precise technical summariser."),
                HumanMessage(content=self._build_summary_prompt(to_summarise)),
            ]
        )
        self._apply_compaction(_msg_text(response.content), keep)

    async def _compact_history_async(self) -> None:
        """Async version of :meth:`_compact_history`."""
        keep = 4
        if self._estimate_tokens() <= self._settings.max_history_tokens:
            return
        to_summarise = self._history[:-keep] if len(self._history) > keep else []
        if not to_summarise:
            return
        logger.info(
            "agent[compaction] async %d tokens > %d limit, compacting %d messages",
            self._estimate_tokens(),
            self._settings.max_history_tokens,
            len(to_summarise),
        )
        response = await self._compaction_llm.ainvoke(
            [
                SystemMessage(content="You are a precise technical summariser."),
                HumanMessage(content=self._build_summary_prompt(to_summarise)),
            ]
        )
        self._apply_compaction(_msg_text(response.content), keep)

    def reset(self) -> None:
        """Clear conversation history, starting a fresh session."""
        self._history = []

    @property
    def history(self) -> list[BaseMessage]:
        """Read-only view of the conversation history."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_input(self) -> AgentState:
        return AgentState(
            messages=list(self._history),
            repo_id=self._repo_id,
            retrieved_context="",
            route="implementation",
        )


# ---------------------------------------------------------------------------
# LangSmith tracing
# ---------------------------------------------------------------------------


def _configure_langsmith(settings: Settings) -> None:
    """Enable LangSmith tracing if an API key is configured."""
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
