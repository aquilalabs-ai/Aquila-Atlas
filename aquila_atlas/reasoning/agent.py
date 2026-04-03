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

_RouteType = Literal["structural", "implementation", "generation", "diagram", "direct"]

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
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """\
You are Aquila, an expert AI assistant specialised in understanding codebases.
Help developers navigate, understand, and reason about source code.

## Answer format

- Be specific and cite file paths and function names from the retrieved context.
- Format code references as `file_path:line_number`.
- Keep answers concise and technical.
- Never give generic answers like "I don't have enough information" or improvising with generic responses without trying to get more context first.
- Always provide a substantive answer. If the pre-fetched context is not enough,
  call a tool (semantic_search, file_reader, get-schema, read-cypher) to get more
  information before responding — do not say you lack context without trying.
- Only admit you cannot answer after you have tried at least one tool call.
"""

# ---------------------------------------------------------------------------
# Skills — focused prompt fragments loaded per query type
# ---------------------------------------------------------------------------

_SKILL_ARCHITECTURE = """\
## Skill: Architecture exploration

You are answering a structural or architectural question.

The system message already contains pre-fetched code context — read it first \
and use it to build your answer.

1. Start from the pre-fetched context in the system message to understand the \
   overall structure (modules, classes, entry points).
2. If graph tools are available, call `read-cypher` for targeted traversals \
   (callers, callees, import chains) — schema context is automatically provided.
3. Use `semantic_search` to find additional relevant files or classes when the \
   pre-fetched context is incomplete.
4. Synthesise everything into a clear architectural overview.

### Tool parameter reference
- `get-schema` — no required parameters.
- `read-cypher` — parameter: `query` (the Cypher read query string; schema context automatically retrieved).
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.

### Strategy
- Always answer from the pre-fetched context first; use tools to fill gaps.
- You may call multiple tools in sequence to build a complete answer.
- If a tool returns an error, adjust the query and retry.
"""

_SKILL_CODE_SEARCH = """\
## Skill: Implementation search

You are finding a specific piece of implementation.

The system message already contains pre-fetched code context — read it first \
before calling any tools.

1. If the pre-fetched context answers the question, respond directly.
2. Otherwise call `semantic_search` with a focused, specific query.
3. Use `file_reader` when you need the full file rather than snippets.
4. Use `read-cypher(query=...)` to trace callers/callees of a found function.
5. If `semantic_search` returns empty, switch to `read-cypher` for graph \
   traversal instead.

### Tool parameter reference
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.
- `read-cypher` — parameter: `query` (the Cypher read query string).

### HARD stop conditions — follow these without exception
- If `semantic_search` returns "No results found" **once**: immediately switch to
  `read-cypher`. Do NOT call `semantic_search` again with a different query.
- If both `semantic_search` and `read-cypher` return nothing: answer directly
  from the pre-fetched context or state what you know. Do NOT loop further.
- Never call the same tool more than twice in a single turn.
"""

_SKILL_DOC = """\
## Skill: Documentation generation

You are generating or improving documentation.

1. Use `summarize` for a plain-English overview of a file, class, or module.
2. Use `generate_docstring` to produce a Google-style docstring for a function \
   or method.
3. Use `semantic_search` or `file_reader` to fetch the source if you need to \
   inspect the code yourself before writing.
4. Return only the requested documentation — no surrounding commentary.

### Tool parameter reference
- `summarize` — parameters: `target` (file path or qualified name), `repo_id`.
- `generate_docstring` — parameters: `function_id` (qualified name), `repo_id`.
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.
"""

_SKILL_DIAGRAM = """\
## Skill: Diagram generation

You are generating a Mermaid diagram that visualises codebase structure.

1. Call `generate_mermaid` with the appropriate `diagram_type`:
   - `'flowchart'`       → file-level import / dependency graph
   - `'classDiagram'`    → class hierarchy and their methods
   - `'sequenceDiagram'` → function call flows between components
2. Set `scope` to a file path or module name if the user asked for a specific area.
3. Set `focus` to a short phrase that captures the user's intent, e.g. `'auth flow'`.
4. The tool returns a validated, fenced ```mermaid block — include it **verbatim** in your answer.
5. After inserting the diagram, add a brief (2-4 sentence) explanation of what it shows.

### Tool parameter reference
- `generate_mermaid` — parameters: `repo_id`, `diagram_type`, optional `scope`, `focus`.
- `semantic_search`   — use only if you need extra context before choosing diagram_type.

### HARD rules
- **Do NOT call `validate_mermaid`** — the diagram is already validated inside `generate_mermaid`.
- **Do NOT call any other tool after receiving the diagram** — just write your answer.
- Do not invent node/class names that are not in the tool-returned data.
- Do not mix diagram types (e.g. classDiagram arrows inside a flowchart).
- Always include at least one sentence of explanation after the diagram.
"""

_SKILL_MAP: dict[str, str] = {
    "structural": _SKILL_ARCHITECTURE,
    "implementation": _SKILL_CODE_SEARCH,
    "generation": _SKILL_DOC,
    "diagram": _SKILL_DIAGRAM,
}

# ---------------------------------------------------------------------------
# Router prompt
# ---------------------------------------------------------------------------

_ROUTER_PROMPT = """\
You are classifying a codebase Q&A query. Reply with ONLY one word from this list:

- "structural"     — architecture, module layout, class hierarchy, call graphs,
  import relationships, "what does this codebase do", "what calls X", "show all classes",
  file counts, file type distribution, "how many X", "are there any Y files",
  repository composition, folder structure
- "implementation" — how an algorithm works, where a function is defined,
  specific logic details, "how does X work", "show me Y", "where is Z", "explain X"
- "generation"     — generate or improve documentation, write a docstring,
  summarise a file or class
- "diagram"        — draw, visualise, or render a diagram, graph, chart, flowchart,
  class diagram, or sequence diagram of the codebase structure or call flows
- "direct"         — ONLY pure greetings ("hi", "hello", "thanks") or requests to
  rephrase/shorten/expand the immediately preceding AI answer; never use "direct"
  for any question about the codebase itself

{context_block}\
Query: {query}
"""

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

    messages: list[BaseMessage] = [SystemMessage(content=system_content), *state["messages"]]
    logger.debug(
        "agent[reasoning] prompt messages=%d system_len=%d",
        len(messages),
        len(system_content),
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

    # Recovery: if the LLM returned empty content with no valid tool calls (e.g. it
    # attempted an invalid/hallucinated tool call or the args were malformed), but
    # there are tool results already in history, force a synthesis pass so the user
    # never receives a blank response.
    if not response_text and not tool_calls:
        from langchain_core.messages import ToolMessage  # noqa: PLC0415

        has_tool_results = any(isinstance(m, ToolMessage) for m in state["messages"])
        if has_tool_results:
            logger.warning(
                "agent[reasoning] empty response after tool results — forcing synthesis pass"
            )
            recovery = llm.invoke(
                messages
                + [
                    HumanMessage(
                        content=(
                            "Your last action produced no output. "
                            "Using the tool results already in this conversation, "
                            "write a complete answer for the user. "
                            "Do not call any more tools."
                        )
                    )
                ]
            )
            if _msg_text(getattr(recovery, "content", "")):
                response = recovery
        else:
            logger.warning("agent[reasoning] LLM returned empty content with no tool calls")

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
        return str(last_ai.content) if last_ai else ""

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
        except TimeoutError:
            logger.warning("CodebaseAgent.astream_with_status timed out after %.0fs", timeout)
            timed_out = True
            if not accumulated:
                yield {
                    "token": "\n\n_Response timed out. Please try again or rephrase your question._"
                }
                accumulated = "(timed out)"

        if not accumulated and last_answer_text:
            accumulated = last_answer_text
            yield {"token": accumulated}

        # Yield final event with token counts (always, so the frontend can clear
        # the "0 / 0" placeholder even when the model doesn't report usage).
        if not timed_out:
            yield {"input_tokens": input_tokens, "output_tokens": output_tokens}

        if not timed_out:
            if accumulated:
                self._history.append(AIMessage(content=accumulated))
            else:
                if self._history and isinstance(self._history[-1], HumanMessage):
                    self._history.pop()
                logger.warning("agent[astream_with_status] empty response for query=%r", query)

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
        return str(last_ai.content) if last_ai else ""

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
        async for event in self._graph.astream_events(self._build_input(), config, version="v2"):
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

            else:
                data = event.get("data", {})
                data_keys = list(data.keys()) if isinstance(data, dict) else type(data)
                logger.debug(
                    "agent[reasoning] event ignored event=%s node=%s data_keys=%s",
                    etype,
                    node,
                    data_keys,
                )

        # Non-streaming / batch endpoints: emit the captured final answer.
        if not accumulated and last_answer_text:
            accumulated = last_answer_text
            yield accumulated

        if accumulated:
            self._history.append(AIMessage(content=accumulated))
        else:
            # No response captured — remove the dangling human message so history
            # stays balanced (avoid consecutive HumanMessages confusing the LLM).
            if self._history and isinstance(self._history[-1], HumanMessage):
                self._history.pop()
            logger.warning("agent[astream] empty accumulated response for query=%r", query)

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
