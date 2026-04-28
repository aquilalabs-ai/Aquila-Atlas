"""JWT token creation and verification for Aquila-Atlas auth.

Access tokens:  HS256, 8-hour TTL, payload {sub, email, role, type: "access"}
Refresh tokens: HS256, 30-day TTL, payload {sub, jti, type: "refresh"}
                The SHA-256 hash of the refresh token is stored in the DB.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast


def create_access_token(user_id: str, email: str, role: str, secret: str) -> str:
    """Return a signed HS256 access token valid for 8 hours."""
    from jose import jwt  # noqa: PLC0415

    now = datetime.now(tz=UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(hours=8),
    }
    return cast("str", jwt.encode(payload, secret, algorithm="HS256"))


def create_refresh_token(user_id: str, secret: str) -> tuple[str, str]:
    """Return ``(token, token_hash)`` for a 30-day refresh token.

    Store ``token_hash`` (SHA-256 hex) in the database; send ``token`` to the
    client.
    """
    from jose import jwt  # noqa: PLC0415

    now = datetime.now(tz=UTC)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=30),
    }
    token = cast("str", jwt.encode(payload, secret, algorithm="HS256"))
    return token, hash_token(token)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and validate an access token.

    Raises :class:`jose.JWTError` on failure (expired, bad signature, wrong
    type, …).
    """
    from jose import JWTError, jwt  # noqa: PLC0415

    payload = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise JWTError("Not an access token")
    return cast("dict[str, Any]", payload)


def decode_refresh_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and validate a refresh token.

    Raises :class:`jose.JWTError` on failure.
    """
    from jose import JWTError, jwt  # noqa: PLC0415

    payload = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("type") != "refresh":
        raise JWTError("Not a refresh token")
    return cast("dict[str, Any]", payload)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token*."""
    return hashlib.sha256(token.encode()).hexdigest()
