"""PostgreSQL-backed auth store for Aquila-Atlas.

Manages users, auth sessions, instance licenses, and repository membership.
Follows the same pattern as :class:`aquila_atlas.api.store.SessionStore`:
synchronous psycopg3, ``_live()`` reconnect, ``_ensure_schema()``.

Tables
------
aquila_instance_license
    One row per validated license JWT (most recent is used at runtime).

aquila_users
    One row per provisioned user.  LDAP users have ``hashed_password = NULL``.

aquila_auth_sessions
    Refresh-token sessions.  Only the SHA-256 hash of the token is stored.

aquila_repo_members
    Per-repo membership/role assignments.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger("aquila.api.auth.store")


class AuthStore:
    """Thin synchronous psycopg3 wrapper for auth-related tables.

    All public methods are synchronous and safe to call from async FastAPI
    handlers — operations are single-row reads/writes that complete in
    microseconds and do not benefit from async I/O.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    # ── Schema ────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        conn = self._conn

        # Instance license — keeps a history; most recent row is used
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_instance_license (
                id            SERIAL PRIMARY KEY,
                customer_id   TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                max_seats     INT  NOT NULL,
                expires_at    TIMESTAMPTZ NOT NULL,
                raw_token     TEXT NOT NULL,
                validated_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        # Users
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_users (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email           TEXT UNIQUE NOT NULL,
                display_name    TEXT NOT NULL DEFAULT '',
                auth_mode       TEXT NOT NULL,
                hashed_password TEXT,
                seat_key_id     TEXT,
                ldap_dn         TEXT,
                role            TEXT NOT NULL DEFAULT 'user',
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                last_seen_at    TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_aquila_users_email ON aquila_users (email)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_users_seat_key_id"
            " ON aquila_users (seat_key_id) WHERE seat_key_id IS NOT NULL"
        )

        # Auth sessions (refresh tokens)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_auth_sessions (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id      UUID NOT NULL,
                token_hash   TEXT NOT NULL UNIQUE,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                expires_at   TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_auth_sessions_user_id"
            " ON aquila_auth_sessions (user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_auth_sessions_expires_at"
            " ON aquila_auth_sessions (expires_at)"
        )

        # Repo membership
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_repo_members (
                repo_id    TEXT NOT NULL,
                user_id    UUID NOT NULL,
                role       TEXT NOT NULL DEFAULT 'member',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (repo_id, user_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_repo_members_user_id"
            " ON aquila_repo_members (user_id)"
        )

    # ── Reconnect ─────────────────────────────────────────────────────────

    def _live(self) -> Any:
        """Return a live connection, reconnecting if the previous one dropped."""
        import psycopg  # noqa: PLC0415

        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    # ── Instance license ──────────────────────────────────────────────────

    def save_license(
        self,
        customer_id: str,
        customer_name: str,
        max_seats: int,
        expires_at: Any,
        raw_token: str,
    ) -> None:
        """Insert a new validated license row."""
        self._live().execute(
            """
            INSERT INTO aquila_instance_license
                (customer_id, customer_name, max_seats, expires_at, raw_token, validated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (customer_id, customer_name, max_seats, expires_at, raw_token),
        )

    def load_license(self) -> dict[str, Any] | None:
        """Return the most recently validated license row, or ``None``."""
        row = (
            self._live()
            .execute(
                """
                SELECT id, customer_id, customer_name, max_seats, expires_at, raw_token, validated_at
                FROM aquila_instance_license
                ORDER BY id DESC
                LIMIT 1
                """
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "id": row[0],
            "customer_id": row[1],
            "customer_name": row[2],
            "max_seats": row[3],
            "expires_at": row[4],
            "raw_token": row[5],
            "validated_at": row[6],
        }

    # ── Users ─────────────────────────────────────────────────────────────

    def count_active_users(self) -> int:
        """Return the number of active (non-deleted) user rows."""
        row = (
            self._live()
            .execute("SELECT COUNT(*) FROM aquila_users WHERE is_active = TRUE")
            .fetchone()
        )
        return int(row[0] if row else 0)

    def create_user(
        self,
        email: str,
        display_name: str,
        auth_mode: str,
        hashed_password: str | None = None,
        seat_key_id: str | None = None,
        ldap_dn: str | None = None,
        role: str = "user",
    ) -> dict[str, Any]:
        """Insert a new user row and return it as a dict."""
        user_id = str(uuid.uuid4())
        email = email.lower()
        self._live().execute(
            """
            INSERT INTO aquila_users
                (id, email, display_name, auth_mode, hashed_password,
                 seat_key_id, ldap_dn, role, is_active, created_at, last_seen_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            """,
            (user_id, email, display_name, auth_mode, hashed_password, seat_key_id, ldap_dn, role),
        )
        result = self.get_user_by_id(user_id)
        assert result is not None  # just inserted
        return result

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Return user dict for *email*, or ``None`` if not found."""
        row = (
            self._live()
            .execute(
                """
                SELECT id, email, display_name, auth_mode, hashed_password,
                       seat_key_id, ldap_dn, role, is_active, created_at, last_seen_at
                FROM aquila_users WHERE LOWER(email) = %s
                """,
                (email.lower(),),
            )
            .fetchone()
        )
        return _user_row_to_dict(row)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Return user dict for *user_id*, or ``None`` if not found."""
        row = (
            self._live()
            .execute(
                """
                SELECT id, email, display_name, auth_mode, hashed_password,
                       seat_key_id, ldap_dn, role, is_active, created_at, last_seen_at
                FROM aquila_users WHERE id = %s
                """,
                (user_id,),
            )
            .fetchone()
        )
        return _user_row_to_dict(row)

    def get_user_by_seat_key_id(self, seat_key_id: str) -> dict[str, Any] | None:
        """Return user dict matching *seat_key_id*, or ``None``."""
        row = (
            self._live()
            .execute(
                """
                SELECT id, email, display_name, auth_mode, hashed_password,
                       seat_key_id, ldap_dn, role, is_active, created_at, last_seen_at
                FROM aquila_users WHERE seat_key_id = %s
                """,
                (seat_key_id,),
            )
            .fetchone()
        )
        return _user_row_to_dict(row)

    def list_users(self) -> list[dict[str, Any]]:
        """Return all user rows ordered by creation date."""
        rows = (
            self._live()
            .execute(
                """
                SELECT id, email, display_name, auth_mode, hashed_password,
                       seat_key_id, ldap_dn, role, is_active, created_at, last_seen_at
                FROM aquila_users
                ORDER BY created_at ASC
                """
            )
            .fetchall()
        )
        return [d for row in rows if (d := _user_row_to_dict(row)) is not None]

    def update_user(self, user_id: str, **kwargs: Any) -> bool:
        """Update mutable user fields.

        Accepted keyword arguments: ``is_active``, ``role``, ``display_name``.
        Returns ``True`` if a row was updated.
        """
        allowed = {"is_active", "role", "display_name"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clauses = ", ".join(f"{col} = %s" for col in updates)
        values = list(updates.values()) + [user_id]
        cur = self._live().execute(
            f"UPDATE aquila_users SET {set_clauses} WHERE id = %s",  # noqa: S608
            values,
        )
        return (cur.rowcount or 0) > 0

    def touch_user(self, user_id: str) -> None:
        """Update ``last_seen_at`` to NOW() for *user_id*."""
        self._live().execute(
            "UPDATE aquila_users SET last_seen_at = NOW() WHERE id = %s",
            (user_id,),
        )

    def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user row.  Returns ``True`` if a row was removed."""
        cur = self._live().execute(
            "DELETE FROM aquila_users WHERE id = %s RETURNING id",
            (user_id,),
        )
        return cur.fetchone() is not None

    # ── Auth sessions ─────────────────────────────────────────────────────

    def create_session(self, user_id: str, token_hash: str, expires_at: Any) -> str:
        """Insert a new auth session row. Returns the session UUID."""
        session_id = str(uuid.uuid4())
        self._live().execute(
            """
            INSERT INTO aquila_auth_sessions
                (id, user_id, token_hash, created_at, expires_at, last_seen_at)
            VALUES (%s, %s, %s, NOW(), %s, NOW())
            """,
            (session_id, user_id, token_hash, expires_at),
        )
        return session_id

    def get_session_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        """Return a non-expired session matching *token_hash*, or ``None``."""
        row = (
            self._live()
            .execute(
                """
                SELECT id, user_id, token_hash, created_at, expires_at, last_seen_at
                FROM aquila_auth_sessions
                WHERE token_hash = %s AND expires_at > NOW()
                """,
                (token_hash,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "user_id": str(row[1]),
            "token_hash": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
            "expires_at": row[4].isoformat() if row[4] else None,
            "last_seen_at": row[5].isoformat() if row[5] else None,
        }

    def delete_session(self, token_hash: str) -> None:
        """Delete the session identified by *token_hash*."""
        self._live().execute(
            "DELETE FROM aquila_auth_sessions WHERE token_hash = %s",
            (token_hash,),
        )

    def delete_user_sessions(self, user_id: str) -> None:
        """Delete all sessions for *user_id* (e.g. on logout-all or deactivation)."""
        self._live().execute(
            "DELETE FROM aquila_auth_sessions WHERE user_id = %s",
            (user_id,),
        )

    # ── Repo membership ───────────────────────────────────────────────────

    def add_repo_member(self, repo_id: str, user_id: str, role: str = "member") -> None:
        """Upsert a membership row.  Updates role if the pair already exists."""
        self._live().execute(
            """
            INSERT INTO aquila_repo_members (repo_id, user_id, role, created_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (repo_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (repo_id, user_id, role),
        )

    def get_repo_member(self, repo_id: str, user_id: str) -> dict[str, Any] | None:
        """Return the membership row for *(repo_id, user_id)*, or ``None``."""
        row = (
            self._live()
            .execute(
                """
                SELECT repo_id, user_id, role, created_at
                FROM aquila_repo_members WHERE repo_id = %s AND user_id = %s
                """,
                (repo_id, user_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "repo_id": row[0],
            "user_id": str(row[1]),
            "role": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        }

    def list_repo_members(self, repo_id: str) -> list[dict[str, Any]]:
        """Return all membership rows for *repo_id*, joined with user info."""
        rows = (
            self._live()
            .execute(
                """
                SELECT rm.repo_id, rm.user_id, rm.role, rm.created_at,
                       u.email, u.display_name
                FROM aquila_repo_members rm
                JOIN aquila_users u ON u.id = rm.user_id
                WHERE rm.repo_id = %s
                ORDER BY rm.created_at ASC
                """,
                (repo_id,),
            )
            .fetchall()
        )
        return [
            {
                "repo_id": row[0],
                "user_id": str(row[1]),
                "role": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "email": row[4],
                "display_name": row[5],
            }
            for row in rows
        ]

    def list_user_repos(self, user_id: str) -> list[str]:
        """Return all repo_ids where *user_id* has any membership."""
        rows = (
            self._live()
            .execute(
                "SELECT repo_id FROM aquila_repo_members WHERE user_id = %s ORDER BY created_at ASC",
                (user_id,),
            )
            .fetchall()
        )
        return [row[0] for row in rows]

    def remove_repo_member(self, repo_id: str, user_id: str) -> bool:
        """Remove a membership row. Returns ``True`` if a row was deleted."""
        cur = self._live().execute(
            "DELETE FROM aquila_repo_members WHERE repo_id = %s AND user_id = %s RETURNING repo_id",
            (repo_id, user_id),
        )
        return cur.fetchone() is not None

    def delete_all_repo_members(self, repo_id: str) -> int:
        """Remove all membership rows for *repo_id*. Returns count deleted."""
        cur = self._live().execute(
            "DELETE FROM aquila_repo_members WHERE repo_id = %s",
            (repo_id,),
        )
        return cur.rowcount or 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_row_to_dict(row: Any) -> dict[str, Any] | None:
    """Convert a raw psycopg row (11 columns) to a user dict."""
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "email": row[1],
        "display_name": row[2],
        "auth_mode": row[3],
        "hashed_password": row[4],
        "seat_key_id": row[5],
        "ldap_dn": row[6],
        "role": row[7],
        "is_active": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "last_seen_at": row[10].isoformat() if row[10] else None,
    }


def create_auth_store(postgres_url: str) -> AuthStore:
    """Connect to PostgreSQL and return a :class:`AuthStore`."""
    return AuthStore(postgres_url)
