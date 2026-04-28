"""Password hashing utilities using bcrypt directly.

passlib 1.7.x has a compatibility issue with bcrypt >= 4.x (missing
``__about__`` attribute).  We call the ``bcrypt`` library directly to avoid
the problem while keeping the same simple ``hash_password`` / ``verify_password``
API the rest of the codebase expects.
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain* (work factor 12)."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` if *plain* matches the bcrypt *hashed* value."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False
