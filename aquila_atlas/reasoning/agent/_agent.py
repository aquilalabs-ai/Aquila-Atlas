"""CodebaseAgent — stateful multi-turn wrapper around the LangGraph pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ._langsmith import _configure_langsmith
from ._nodes import _msg_text
from ._prompts import _NODE_STATUS, _SYSTEM_PROMPT_BASE, _TOOL_STATUS

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from langchain_core.tools import BaseTool

    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService


class AgentStreamEvent(TypedDict, total=False):
    """Discriminated event emitted by :meth:`CodebaseAgent.astream_with_status`.

    Exactly one of ``token`` or ``status`` is set per event.
    """

    token: str
    status: str
    input_tokens: int
    output_tokens: int


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
        security_store: object | None = None,
    ) -> None:
        from aquila_atlas.config import get_settings  # noqa: PLC0415
        from aquila_atlas.reasoning.llm import get_chat_model  # noqa: PLC0415

        from ._graph import build_graph
        from ._state import AgentState  # noqa: F401

        s = settings or get_settings()
        _configure_langsmith(s)
        self._graph = build_graph(
            service, s, extra_tools=extra_tools, security_store=security_store
        )
        self._repo_id = repo_id
        self._history: list[BaseMessage] = []
        self._settings = s
        # Lightweight LLM used only for history compaction (no tools bound).
        self._compaction_llm = get_chat_model(s)

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
                isinstance(metadata, dict)
                and metadata.get("langgraph_node") == "reasoning"
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

        Yields dicts — each has either a ``token`` key (LLM output fragment)
        or a ``status`` key (human-readable progress label such as
        *"Searching codebase..."*).  Used by the SSE chat endpoint so the UI
        can show the user what the agent is doing instead of a blank screen.

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
                        # Only stream tokens produced by the reasoning node.
                        # Tool-internal LLM calls (summarize, generate_mermaid, …) run
                        # inside the "tools" ToolNode — their chunks must not leak into
                        # the user-facing stream.
                        if node and node != "reasoning":
                            continue
                        chunk = event["data"].get("chunk")
                        text = _msg_text(getattr(chunk, "content", chunk))
                        if text:
                            accumulated += text
                            yield {"token": text}

                    elif etype in {"on_chat_model_end", "on_llm_end"}:
                        output = event["data"].get("output") or event["data"].get("content")
                        if output is not None:
                            # Accumulate token usage from ALL LLM calls (router, tools, …).
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

                            # Only update last_answer_text from the reasoning node so
                            # tool-internal LLM responses (summarize, etc.) don't
                            # overwrite the real final answer.
                            if node in ("reasoning", ""):
                                text = _msg_text(getattr(output, "content", output))
                                if text:
                                    last_answer_text = text

                    elif etype == "on_chain_end" and node == "reasoning":
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
        except asyncio.CancelledError:
            # The HTTP request was cancelled (client disconnected).  Roll back the
            # user message that was already appended so history stays consistent.
            logger.info(
                "CodebaseAgent.astream_with_status cancelled (client disconnected) repo=%s",
                self._repo_id,
            )
            if self._history and isinstance(self._history[-1], HumanMessage):
                self._history.pop()
            raise  # propagate so the SSE generator can close cleanly
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
            else:
                raise

        if not accumulated and last_answer_text:
            accumulated = last_answer_text
            yield {"token": accumulated}

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
        """Re-invoke the plain LLM (no tools) when the graph returns an empty response."""
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

    def _build_input(self) -> dict[str, Any]:
        return {
            "messages": list(self._history),
            "repo_id": self._repo_id,
            "retrieved_context": "",
            "route": "implementation",
        }
