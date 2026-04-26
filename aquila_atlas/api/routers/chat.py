"""Chat endpoints — multi-turn codebase Q&A with session management."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from aquila_atlas.api.deps import Auth, SessionMeta, Sessions, Store, Svc  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine

    from langchain_core.tools import BaseTool
from aquila_atlas.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDeleteResponse,
    SessionInfo,
    SessionListResponse,
    SessionResetResponse,
    SessionStoreInfo,
)

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService
    from aquila_atlas.reasoning.agent import CodebaseAgent

router = APIRouter(prefix="/repos", tags=["Chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_meta(session_id: str, repo_id: str, title: str) -> dict:  # type: ignore[type-arg]
    return {
        "session_id": session_id,
        "repo_id": repo_id,
        "title": title,
        "created_at": _now_iso(),
        "message_count": 0,
    }


def _create_session(
    sessions: dict[str, CodebaseAgent],
    session_meta: dict[str, dict],  # type: ignore[type-arg]
    session_id: str,
    repo_id: str,
    svc: KnowledgeService,
    title: str = "New Chat",
    extra_tools: list[BaseTool] | None = None,
    security_store: object | None = None,
) -> CodebaseAgent:
    from aquila_atlas.reasoning.agent import CodebaseAgent as _Agent  # noqa: PLC0415

    agent = _Agent(
        service=svc, repo_id=repo_id, extra_tools=extra_tools, security_store=security_store
    )
    sessions[session_id] = agent
    session_meta[session_id] = _make_meta(session_id, repo_id, title)
    return agent


def _get_or_create_agent(
    sessions: dict[str, CodebaseAgent],
    session_meta: dict[str, dict],  # type: ignore[type-arg]
    session_id: str,
    repo_id: str,
    svc: KnowledgeService,
    store: Any = None,
    extra_tools: list[BaseTool] | None = None,
    security_store: object | None = None,
) -> CodebaseAgent:
    if session_id not in sessions:
        agent = _create_session(
            sessions,
            session_meta,
            session_id,
            repo_id,
            svc,
            extra_tools=extra_tools,
            security_store=security_store,
        )
        # Restore persisted state from Valkey (survives server restarts)
        if store is not None:
            persisted_meta = store.load_meta(session_id)
            if persisted_meta:
                session_meta[session_id] = persisted_meta
            history = store.load_history(session_id)
            if history:
                agent.set_history(history)
        return agent
    return sessions[session_id]


def _auto_title(message: str, max_len: int = 60) -> str:
    """Use the first user message (trimmed) as a human-readable session title."""
    title = message.strip().splitlines()[0]
    return title[:max_len] + ("…" if len(title) > max_len else "")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{repo_id}/sessions",
    response_model=SessionCreateResponse,
    summary="Create a new chat session",
    status_code=status.HTTP_201_CREATED,
    description=(
        "Explicitly create a named session for *repo_id* and return its ID. "
        "Use this when the user clicks **New Conversation** — the returned "
        "`session_id` should be passed in subsequent `POST /repos/{repo_id}/chat` calls. "
        "This guarantees a clean history rather than relying on the client to omit `session_id`."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
async def create_session(
    repo_id: str,
    req: SessionCreateRequest,
    request: Request,
    svc: Svc,
    sessions: Sessions,
    session_meta: SessionMeta,
    store: Store,
    _auth: Auth,
) -> SessionCreateResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    session_id = str(uuid.uuid4())
    _create_session(
        sessions,
        session_meta,
        session_id,
        repo_id,
        svc,
        title=req.title,
        extra_tools=getattr(request.app.state, "mcp_tools", None) or None,
        security_store=getattr(request.app.state, "security_store", None),
    )
    meta = session_meta[session_id]
    if store is not None:
        store.save_meta(session_id, meta)
    return SessionCreateResponse(
        session_id=session_id,
        repo_id=repo_id,
        title=meta["title"],
        created_at=meta["created_at"],
    )


@router.post(
    "/{repo_id}/chat",
    response_model=None,
    summary="Send a chat message",
    description=(
        "Send a natural language question about the repository and receive an AI-generated "
        "answer grounded in the ingested code.\n\n"
        "**Streaming (default):** Set `stream: true` to receive a `text/event-stream` "
        "response. Each SSE event carries a JSON payload:\n"
        "```json\n"
        'data: {"token": "...", "session_id": "..."}\n'
        "```\n"
        "A final event signals completion:\n"
        "```json\n"
        'data: {"done": true, "session_id": "..."}\n'
        "```\n\n"
        "**Non-streaming:** Set `stream: false` for a plain JSON `ChatResponse`.\n\n"
        "Pass `session_id` from a previous response to continue a conversation. "
        "Omit it (or call `POST /repos/{repo_id}/sessions` first) to start fresh."
    ),
    responses={
        200: {
            "description": "Streaming SSE or JSON chat response",
            "content": {
                "text/event-stream": {
                    "example": 'data: {"token": "The auth", "session_id": "abc"}\n\n'
                },
                "application/json": {
                    "example": {
                        "response": "Authentication is handled in `src/auth/service.py:42`…",
                        "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                    }
                },
            },
        },
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
async def chat(
    repo_id: str,
    req: ChatRequest,
    request: Request,
    svc: Svc,
    sessions: Sessions,
    session_meta: SessionMeta,
    store: Store,
    _auth: Auth,
) -> StreamingResponse | ChatResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    session_id = req.session_id or str(uuid.uuid4())
    agent = _get_or_create_agent(
        sessions,
        session_meta,
        session_id,
        repo_id,
        svc,
        store=store,
        extra_tools=getattr(request.app.state, "mcp_tools", None) or None,
        security_store=getattr(request.app.state, "security_store", None),
    )
    meta = session_meta[session_id]

    # Set title from the first user message
    if meta["message_count"] == 0:
        meta["title"] = _auto_title(req.message)

    if req.stream:

        async def _token_stream() -> AsyncIterator[str]:
            import logging  # noqa: PLC0415

            log = logging.getLogger("aquila.api")
            input_tokens = 0
            output_tokens = 0

            # Merge the agent stream with a periodic keepalive so long-running
            # tool calls (e.g. generate_mermaid with multiple LLM retries) don't
            # cause the browser to drop the SSE connection due to inactivity.
            _KEEPALIVE_INTERVAL = 20.0  # seconds between SSE comment pings

            agent_iter = agent.astream_with_status(req.message).__aiter__()
            next_event: asyncio.Task[Any] | None = None

            try:
                next_event = asyncio.create_task(
                    cast("Coroutine[Any, Any, Any]", agent_iter.__anext__())
                )
                while True:
                    done, _ = await asyncio.wait({next_event}, timeout=_KEEPALIVE_INTERVAL)
                    if not done:
                        # No event yet — send an SSE comment to keep the connection alive.
                        yield ": ping\n\n"
                        continue

                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        break

                    if event.get("status"):
                        yield f"data: {json.dumps({'status': event['status'], 'session_id': session_id})}\n\n"
                    if event.get("token"):
                        yield f"data: {json.dumps({'token': event['token'], 'session_id': session_id})}\n\n"
                    if event.get("input_tokens") is not None:
                        input_tokens = event["input_tokens"]
                    if event.get("output_tokens") is not None:
                        output_tokens = event["output_tokens"]

                    next_event = asyncio.create_task(
                        cast("Coroutine[Any, Any, Any]", agent_iter.__anext__())
                    )

            except asyncio.CancelledError:
                log.info("SSE stream cancelled for session=%s (client disconnected)", session_id)
                if next_event is not None and not next_event.done():
                    next_event.cancel()
                return
            finally:
                if next_event is not None and not next_event.done():
                    next_event.cancel()

            meta["message_count"] += 1
            # Persist history + metadata after every completed turn.
            if store is not None:
                store.save_history(session_id, agent.get_history())
                store.save_meta(session_id, meta)
            yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'input_tokens': input_tokens, 'output_tokens': output_tokens})}\n\n"

        return StreamingResponse(
            _token_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-ID": session_id,
            },
        )

    response_text = await agent.achat(req.message)
    meta["message_count"] += 1
    if store is not None:
        store.save_history(session_id, agent.get_history())
        store.save_meta(session_id, meta)
    return ChatResponse(response=response_text, session_id=session_id)


@router.get(
    "/{repo_id}/sessions",
    response_model=SessionListResponse,
    summary="List sessions for a repo",
    description=(
        "Returns all live sessions for *repo_id* with their metadata "
        "(title, creation time, message count). Sessions are ordered newest-first."
    ),
    responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}},
)
def list_sessions(
    repo_id: str,
    request: Request,
    session_meta: SessionMeta,
    store: Store,
    _auth: Auth,
) -> SessionListResponse:
    # Merge Valkey (all-time) with in-memory (current run) — Valkey wins on conflict
    merged: dict[str, dict] = {  # type: ignore[type-arg]
        m["session_id"]: m for m in session_meta.values() if m.get("repo_id") == repo_id
    }
    if store is not None:
        for m in store.list_repo_sessions(repo_id):
            merged[m["session_id"]] = m  # Valkey copy is authoritative
    matching = [SessionInfo(**m) for m in merged.values()]
    matching.sort(key=lambda s: s.created_at, reverse=True)
    return SessionListResponse(repo_id=repo_id, sessions=matching, total=len(matching))


@router.get(
    "/{repo_id}/sessions/store",
    response_model=SessionStoreInfo,
    summary="Get persisted chat session store stats",
    description=(
        "Return PostgreSQL-backed session counts for the requested repo and "
        "overall persisted sessions. Requires the session store to be available."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        503: {"model": ErrorResponse, "description": "Session store unavailable"},
    },
)
def get_session_store_info(
    repo_id: str,
    request: Request,
    store: Store,
    _auth: Auth,
) -> SessionStoreInfo:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL session store unavailable",
        )

    return SessionStoreInfo(
        repo_id=repo_id,
        repo_sessions=store.count_sessions(repo_id),
        total_sessions=store.count_sessions(),
        sessions_by_repo=store.list_repo_session_counts(),
    )


@router.post(
    "/{repo_id}/sessions/{session_id}/reset",
    response_model=SessionResetResponse,
    summary="Reset a session's conversation history",
    description=(
        "Clears the agent's memory for *session_id* without deleting the session. "
        "Call this when the user clicks **New Conversation** inside an existing chat "
        "tab — the session_id stays the same but history starts fresh."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
def reset_session(
    repo_id: str,
    session_id: str,
    request: Request,
    sessions: Sessions,
    session_meta: SessionMeta,
    _auth: Auth,
) -> SessionResetResponse:
    if session_id not in sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    sessions[session_id].reset()
    if session_id in session_meta:
        session_meta[session_id]["message_count"] = 0
        session_meta[session_id]["title"] = "New Chat"
        session_meta[session_id]["created_at"] = _now_iso()
    return SessionResetResponse(session_id=session_id, cleared=True)


@router.delete(
    "/{repo_id}/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    summary="Delete a chat session",
    description=(
        "Removes the session and its conversation history from server memory. "
        "Subsequent calls with the same `session_id` will start a fresh conversation."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
def delete_session(
    repo_id: str,
    session_id: str,
    request: Request,
    sessions: Sessions,
    session_meta: SessionMeta,
    store: Store,
    _auth: Auth,
) -> SessionDeleteResponse:
    # A session may exist only in Valkey (from a previous server run) — allow
    # deleting it even if it's not currently loaded in memory.
    in_memory = session_id in sessions
    in_store = store is not None and store.load_meta(session_id) is not None

    if not in_memory and not in_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    sessions.pop(session_id, None)
    session_meta.pop(session_id, None)
    if store is not None:
        store.delete_session(session_id, repo_id)
    return SessionDeleteResponse(session_id=session_id, deleted=True)
