"""Authentication endpoints for Aquila-Atlas.

Handles seat-key activation, login (key + LDAP), token refresh, and logout.
All endpoints are no-ops or return 501 when ``AUTH_MODE=disabled``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from aquila_atlas.api.models import (
    ActivateRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserInfo,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _check_auth_enabled() -> None:
    """Raise 501 when AUTH_MODE is disabled."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    if get_settings().auth_mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Authentication is disabled (AUTH_MODE=disabled)",
        )


def _get_auth_store(request: Request) -> Any:
    """Return auth store or raise 503."""
    store = getattr(request.app.state, "auth_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth store unavailable — check PostgreSQL connection",
        )
    return store


def _issue_tokens(user: dict[str, Any], secret: str) -> TokenResponse:
    """Create access + refresh tokens for *user* and return a :class:`TokenResponse`."""
    from aquila_atlas.api.auth.tokens import (  # noqa: PLC0415
        create_access_token,
        create_refresh_token,
    )

    access = create_access_token(user["id"], user["email"], user["role"], secret)
    refresh, _ = create_refresh_token(user["id"], secret)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
    )


def _store_refresh_session(auth_store: Any, user_id: str, refresh_token: str, secret: str) -> None:
    """Hash the refresh token and persist the session."""
    from aquila_atlas.api.auth.tokens import decode_refresh_token, hash_token  # noqa: PLC0415

    token_hash = hash_token(refresh_token)
    payload = decode_refresh_token(refresh_token, secret)
    exp_ts = payload.get("exp", 0)
    expires_at = datetime.fromtimestamp(exp_ts, tz=UTC)
    auth_store.create_session(user_id, token_hash, expires_at)


# ---------------------------------------------------------------------------
# POST /auth/activate
# ---------------------------------------------------------------------------


@router.post(
    "/activate",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Activate a seat key",
    description=(
        "Validate a vendor-issued seat key JWT, create a new user account, "
        "and return access + refresh tokens. Only available when AUTH_MODE includes 'key'."
    ),
)
def activate(body: ActivateRequest, request: Request) -> TokenResponse:
    _check_auth_enabled()
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.auth_mode not in ("key", "both"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat key activation is only available in 'key' or 'both' auth modes",
        )

    auth_store = _get_auth_store(request)

    # 1. Validate seat key JWT (seat keys have seat_id, not customer_name)
    from aquila_atlas.api.auth.license import LicenseError, validate_seat_key  # noqa: PLC0415

    try:
        key_payload = validate_seat_key(body.seat_key, settings.aquila_vendor_public_key)
    except LicenseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid seat key: {exc}",
        ) from exc

    # seat keys must have seat_id and customer_id (and optionally email)
    seat_id: str = key_payload.get("seat_id", "")
    customer_id: str = key_payload.get("customer_id", "")
    if not seat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat key missing 'seat_id' claim",
        )

    # 2. Email claim check (if key specifies an email it must match)
    key_email: str = key_payload.get("email", "")
    if key_email and key_email.lower() != body.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email does not match the seat key",
        )

    # 3. Check seat_key_id not already used
    existing = auth_store.get_user_by_seat_key_id(seat_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This seat key has already been activated",
        )

    # 4. Check email not already registered
    if auth_store.get_user_by_email(body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # 5. Seat capacity check against the instance license
    lic = auth_store.load_license()
    if lic is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No valid instance license found — contact your administrator",
        )
    now_utc = datetime.now(tz=UTC)
    if lic["expires_at"] < now_utc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instance license has expired",
        )
    # Verify the seat key belongs to this instance
    if customer_id and lic["customer_id"] != customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat key customer_id does not match instance license",
        )
    if auth_store.count_active_users() >= lic["max_seats"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Maximum seat count reached — contact your administrator",
        )

    # 6. Hash password and create user.
    # First user to activate automatically gets admin role (bootstraps the instance).
    from aquila_atlas.api.auth.password import hash_password  # noqa: PLC0415

    is_first_user = auth_store.count_active_users() == 0
    display = body.display_name or body.email.split("@")[0]
    user = auth_store.create_user(
        email=body.email,
        display_name=display,
        auth_mode="key",
        hashed_password=hash_password(body.password),
        seat_key_id=seat_id,
        role="admin" if is_first_user else "user",
    )

    # 7. Issue tokens
    tokens = _issue_tokens(user, settings.aquila_jwt_secret)
    _store_refresh_session(auth_store, user["id"], tokens.refresh_token, settings.aquila_jwt_secret)
    return tokens


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
    description=(
        "Authenticate with email + password (mode='key') or AD credentials (mode='ldap'). "
        "Returns access and refresh tokens."
    ),
)
def login(body: LoginRequest, request: Request) -> TokenResponse:
    _check_auth_enabled()
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    auth_store = _get_auth_store(request)

    if body.mode == "key":
        if settings.auth_mode not in ("key", "both"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Key-mode login is not enabled (AUTH_MODE does not include 'key')",
            )
        user = auth_store.get_user_by_email(body.username)
        if not user or user["auth_mode"] != "key":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )
        from aquila_atlas.api.auth.password import verify_password  # noqa: PLC0415

        if not user["hashed_password"] or not verify_password(
            body.password, user["hashed_password"]
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

    elif body.mode == "ldap":
        if settings.auth_mode not in ("ldap", "both"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LDAP login is not enabled (AUTH_MODE does not include 'ldap')",
            )
        from aquila_atlas.api.auth.ldap import ldap_authenticate  # noqa: PLC0415

        ldap_info = ldap_authenticate(body.username, body.password, settings)
        if ldap_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid LDAP credentials or access denied",
            )

        # Upsert user on first LDAP login
        user = auth_store.get_user_by_email(ldap_info["email"])
        if user is None:
            # Check seat capacity before auto-provisioning
            lic = auth_store.load_license()
            if lic is not None and auth_store.count_active_users() >= lic["max_seats"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Maximum seat count reached — contact your administrator",
                )
            user = auth_store.create_user(
                email=ldap_info["email"],
                display_name=ldap_info["display_name"],
                auth_mode="ldap",
                ldap_dn=ldap_info["dn"],
            )
        else:
            # Refresh display_name and ldap_dn on subsequent logins
            auth_store.update_user(
                user["id"],
                display_name=ldap_info["display_name"],
            )
            if not user["is_active"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is deactivated",
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown login mode '{body.mode}'. Use 'key' or 'ldap'.",
        )

    tokens = _issue_tokens(user, settings.aquila_jwt_secret)
    _store_refresh_session(auth_store, user["id"], tokens.refresh_token, settings.aquila_jwt_secret)
    return tokens


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access + refresh token pair.",
)
def refresh_token(body: RefreshRequest, request: Request) -> TokenResponse:
    _check_auth_enabled()
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    auth_store = _get_auth_store(request)

    from aquila_atlas.api.auth.tokens import decode_refresh_token, hash_token  # noqa: PLC0415

    try:
        decode_refresh_token(body.refresh_token, settings.aquila_jwt_secret)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from None

    token_hash = hash_token(body.refresh_token)
    session = auth_store.get_session_by_token_hash(token_hash)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or expired",
        )

    user = auth_store.get_user_by_id(session["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Rotate: revoke old refresh token, issue new pair
    auth_store.delete_session(token_hash)
    tokens = _issue_tokens(user, settings.aquila_jwt_secret)
    _store_refresh_session(auth_store, user["id"], tokens.refresh_token, settings.aquila_jwt_secret)
    return tokens


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
    description="Revoke the supplied refresh token (invalidates this session only).",
)
def logout(body: RefreshRequest, request: Request) -> None:
    _check_auth_enabled()
    auth_store = _get_auth_store(request)

    from aquila_atlas.api.auth.tokens import hash_token  # noqa: PLC0415

    token_hash = hash_token(body.refresh_token)
    auth_store.delete_session(token_hash)
    # Always return 204 — don't leak whether the token existed


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserInfo,
    summary="Current user info",
    description="Return profile information for the currently authenticated user.",
)
async def me(request: Request) -> UserInfo:
    _check_auth_enabled()
    from aquila_atlas.api.deps import get_current_user  # noqa: PLC0415

    user = await get_current_user(request, request.headers.get("authorization"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return UserInfo(
        user_id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=user["role"],
        auth_mode=user["auth_mode"],
        is_active=user["is_active"],
        created_at=user["created_at"] or "",
        last_seen_at=user["last_seen_at"],
    )
