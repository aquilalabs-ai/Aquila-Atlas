"""Instance license validation for Aquila-Atlas.

The vendor issues RS256-signed JWTs containing customer and seat information.
The matching public key is loaded from ``AQUILA_VENDOR_PUBLIC_KEY`` in ``.env``
and used for offline validation — no call-home is ever made.

Generate a key pair with:

    python scripts/generate_keypair.py

Set the public key in ``.env`` (encode newlines as ``\\n`` inside double quotes):

    AQUILA_VENDOR_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\nMIIBIjAN...\\n-----END PUBLIC KEY-----"

Keep ``vendor_private_key.pem`` secret on the signing machine.
"""

from __future__ import annotations

import logging
from typing import Any, cast

_log = logging.getLogger("aquila.auth.license")


class LicenseError(Exception):
    """Raised when an instance license JWT is invalid or missing required fields."""


def validate_instance_license(token: str, vendor_public_key: str = "") -> dict[str, Any]:
    """Decode and validate an RS256-signed instance license JWT.

    Parameters
    ----------
    token:
        The raw JWT string (base64url-encoded RS256 token).
    vendor_public_key:
        PEM-encoded RSA public key loaded from ``AQUILA_VENDOR_PUBLIC_KEY``.
        Must not be empty when called.

    Returns
    -------
    dict
        Decoded payload with at least ``customer_id``, ``customer_name``,
        ``max_seats``, and ``exp``.

    Raises
    ------
    LicenseError
        If the token is expired, has an invalid signature, is missing
        required fields, or no public key is configured.
    """
    from jose import JWTError, jwt  # noqa: PLC0415

    key = vendor_public_key.strip() if vendor_public_key.strip() else ""
    if not key:
        raise LicenseError(
            "No vendor public key configured. "
            "Set AQUILA_VENDOR_PUBLIC_KEY in .env (see .env.example for format)."
        )

    try:
        payload = jwt.decode(token, key, algorithms=["RS256"])
    except JWTError as exc:
        raise LicenseError(str(exc)) from exc

    required = {"customer_id", "customer_name", "max_seats", "exp"}
    missing = required - payload.keys()
    if missing:
        raise LicenseError(f"License missing required fields: {', '.join(sorted(missing))}")

    return cast("dict[str, Any]", payload)


def validate_seat_key(token: str, vendor_public_key: str = "") -> dict[str, Any]:
    """Decode and validate an RS256-signed seat key JWT.

    Seat keys are issued per-user and carry ``seat_id`` + ``customer_id``.
    They intentionally do *not* contain ``customer_name`` or ``max_seats``.

    Returns
    -------
    dict
        Decoded payload with at least ``customer_id``, ``seat_id``, and ``exp``.

    Raises
    ------
    LicenseError
        If the token is expired, has an invalid signature, or is missing
        required fields.
    """
    from jose import JWTError, jwt  # noqa: PLC0415

    key = vendor_public_key.strip() if vendor_public_key.strip() else ""
    if not key:
        raise LicenseError(
            "No vendor public key configured. "
            "Set AQUILA_VENDOR_PUBLIC_KEY in .env (see .env.example for format)."
        )

    try:
        payload = jwt.decode(token, key, algorithms=["RS256"])
    except JWTError as exc:
        raise LicenseError(str(exc)) from exc

    required = {"customer_id", "seat_id", "exp"}
    missing = required - payload.keys()
    if missing:
        raise LicenseError(f"Seat key missing required fields: {', '.join(sorted(missing))}")

    return cast("dict[str, Any]", payload)
