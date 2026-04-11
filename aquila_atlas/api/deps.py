"""FastAPI dependency providers for auth and shared state."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from aquila_atlas.api.store import SessionStore
from aquila_atlas.knowledge.service import KnowledgeService
from aquila_atlas.reasoning.agent import CodebaseAgent

# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Validate X-API-Key header when a key is configured in settings.

    If ``settings.api_key`` is empty the check is skipped (dev / open mode).
    """
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    configured_key = get_settings().api_key
    if not configured_key:
        return  # open mode — no auth required
    if x_api_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )


Auth = Annotated[None, Depends(require_api_key)]


# ---------------------------------------------------------------------------
# Shared service
# ---------------------------------------------------------------------------


def get_svc(request: Request) -> KnowledgeService:
    """Return the :class:`KnowledgeService` stored on ``app.state``."""
    svc: KnowledgeService = request.app.state.svc
    return svc


Svc = Annotated[KnowledgeService, Depends(get_svc)]


# ---------------------------------------------------------------------------
# Agent sessions
# ---------------------------------------------------------------------------


def get_sessions(request: Request) -> dict[str, CodebaseAgent]:
    """Return the agent session registry stored on ``app.state``."""
    sessions: dict[str, CodebaseAgent] = request.app.state.sessions
    return sessions


Sessions = Annotated[dict[str, CodebaseAgent], Depends(get_sessions)]


def get_session_meta(request: Request) -> dict[str, dict]:  # type: ignore[type-arg]
    """Return the session metadata store (titles, timestamps, message counts)."""
    meta: dict[str, dict] = request.app.state.session_meta  # type: ignore[type-arg]
    return meta


SessionMeta = Annotated[dict[str, dict], Depends(get_session_meta)]  # type: ignore[type-arg]


def get_store(request: Request) -> SessionStore | None:
    """Return the Valkey-backed :class:`SessionStore` from ``app.state``."""
    store: SessionStore | None = request.app.state.store
    return store


Store = Annotated[SessionStore | None, Depends(get_store)]
