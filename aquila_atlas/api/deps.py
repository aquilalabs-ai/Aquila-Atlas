"""FastAPI dependency providers for auth and shared state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from aquila_atlas.api.auth.store import AuthStore
from aquila_atlas.api.store import SessionStore
from aquila_atlas.knowledge.service import KnowledgeService
from aquila_atlas.reasoning.agent import CodebaseAgent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# ---------------------------------------------------------------------------
# API key auth (legacy / opt-in via API_KEY env var)
# ---------------------------------------------------------------------------


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Validate X-API-Key header when a key is configured in settings.

    If ``settings.api_key`` is empty the check is skipped (dev / open mode).
    """
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    configured_key = get_settings().api_key.strip()
    if not configured_key:
        return  # open mode — no auth required
    if x_api_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )


Auth = Annotated[None, Depends(require_api_key)]

# ---------------------------------------------------------------------------
# Auth store dependency
# ---------------------------------------------------------------------------


def get_auth_store(request: Request) -> AuthStore | None:
    store = getattr(request.app.state, "auth_store", None)
    if isinstance(store, AuthStore):
        return store
    return None


AuthStoreD = Annotated[AuthStore | None, Depends(get_auth_store)]

# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | None:
    """Return the current user dict, or ``None`` when auth is disabled.

    Raises HTTP 401 on invalid / missing token when auth is enabled.
    """
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.auth_mode == "disabled":
        return None

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization.removeprefix("Bearer ")

    try:
        from aquila_atlas.api.auth.tokens import decode_access_token  # noqa: PLC0415

        payload = decode_access_token(token, settings.aquila_jwt_secret)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from None

    auth_store = get_auth_store(request)
    if auth_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth store unavailable",
        )

    user = auth_store.get_user_by_id(payload["sub"])
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    auth_store.touch_user(user["id"])
    return user


CurrentUser = Annotated[dict[str, Any] | None, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> dict[str, Any]:
    """Enforce admin role.  Pass-through when auth is disabled."""
    if user is None:
        return {}  # auth disabled — pass through
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


def require_repo_access(min_role: str = "viewer") -> Callable[..., Awaitable[None]]:
    """Return a FastAPI dependency that checks the current user can access *repo_id*.

    Role hierarchy (ascending): viewer < member < owner.
    Admins always pass.  When auth is disabled, always passes.
    """

    async def _dep(repo_id: str, user: CurrentUser, request: Request) -> None:
        if user is None:
            return  # auth disabled
        if user.get("role") == "admin":
            return  # admins see everything

        auth_store = get_auth_store(request)
        if auth_store is None:
            return  # store not available — degrade gracefully

        member = auth_store.get_repo_member(repo_id, user["id"])
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this repository",
            )

        roles = ["viewer", "member", "owner"]
        member_role = member.get("role", "viewer")
        if member_role not in roles:
            member_role = "viewer"
        if roles.index(member_role) < roles.index(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{min_role}' role or higher",
            )

    return _dep


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
