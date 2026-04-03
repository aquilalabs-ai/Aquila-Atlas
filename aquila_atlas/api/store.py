"""PostgreSQL-backed session store.

Persists chat session metadata and agent conversation history so that sessions
survive server restarts.  Uses the synchronous ``psycopg`` (psycopg3) client.

Table schema (auto-created on first connection)
------------------------------------------------
``aquila_sessions``
    session_id  TEXT PRIMARY KEY
    repo_id     TEXT NOT NULL
    meta        TEXT NOT NULL   — JSON dict of session metadata
    history     TEXT NOT NULL   — JSON list of serialised LangChain messages
    expires_at  TIMESTAMPTZ NOT NULL
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = logging.getLogger("aquila.api.store")

_TTL = "30 days"


class SessionStore:
    """Thin wrapper around a synchronous psycopg connection.

    All public methods are synchronous and safe to call from async FastAPI
    handlers — the operations are single-row reads/writes that complete in
    microseconds and do not benefit from async I/O.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_sessions (
                session_id TEXT PRIMARY KEY,
                repo_id    TEXT NOT NULL,
                meta       TEXT NOT NULL DEFAULT '{}',
                history    TEXT NOT NULL DEFAULT '[]',
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_sessions_repo ON aquila_sessions (repo_id)"
        )

    def _live(self) -> Any:
        """Return a live connection, reconnecting if the previous one dropped."""
        import psycopg  # noqa: PLC0415

        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    # ── Metadata ──────────────────────────────────────────────────────────

    def save_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        self._live().execute(
            """
            INSERT INTO aquila_sessions (session_id, repo_id, meta, history, expires_at)
            VALUES (%s, %s, %s, '[]', NOW() + %s::INTERVAL)
            ON CONFLICT (session_id) DO UPDATE
                SET meta       = EXCLUDED.meta,
                    repo_id    = EXCLUDED.repo_id,
                    expires_at = EXCLUDED.expires_at
            """,
            (session_id, meta.get("repo_id", ""), json.dumps(meta), _TTL),
        )

    def load_meta(self, session_id: str) -> dict[str, Any] | None:
        row = (
            self._live()
            .execute(
                "SELECT meta FROM aquila_sessions WHERE session_id = %s AND expires_at > NOW()",
                (session_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return json.loads(row[0])  # type: ignore[return-value]

    def list_repo_sessions(self, repo_id: str) -> list[dict[str, Any]]:
        """Return metadata for every non-expired session belonging to *repo_id*."""
        rows = (
            self._live()
            .execute(
                "SELECT meta FROM aquila_sessions WHERE repo_id = %s AND expires_at > NOW()",
                (repo_id,),
            )
            .fetchall()
        )
        return [json.loads(row[0]) for row in rows]

    def count_sessions(self, repo_id: str | None = None) -> int:
        """Return the number of non-expired persisted sessions."""
        if repo_id is None:
            row = (
                self._live()
                .execute("SELECT COUNT(*) FROM aquila_sessions WHERE expires_at > NOW()")
                .fetchone()
            )
        else:
            row = (
                self._live()
                .execute(
                    "SELECT COUNT(*) FROM aquila_sessions"
                    " WHERE repo_id = %s AND expires_at > NOW()",
                    (repo_id,),
                )
                .fetchone()
            )
        return int(row[0] if row else 0)

    def list_repo_session_counts(self) -> dict[str, int]:
        """Return counts of non-expired sessions grouped by repo_id."""
        rows = (
            self._live()
            .execute(
                "SELECT repo_id, COUNT(*) FROM aquila_sessions"
                " WHERE expires_at > NOW()"
                " GROUP BY repo_id",
            )
            .fetchall()
        )
        return {row[0]: int(row[1]) for row in rows}

    # ── History ───────────────────────────────────────────────────────────

    def save_history(self, session_id: str, messages: list[BaseMessage]) -> None:
        from langchain_core.messages import messages_to_dict  # noqa: PLC0415

        serialised = json.dumps(messages_to_dict(messages))
        self._live().execute(
            """
            UPDATE aquila_sessions
            SET history = %s, expires_at = NOW() + %s::INTERVAL
            WHERE session_id = %s
            """,
            (serialised, _TTL, session_id),
        )

    def load_history(self, session_id: str) -> list[BaseMessage]:
        from langchain_core.messages import messages_from_dict  # noqa: PLC0415

        row = (
            self._live()
            .execute(
                "SELECT history FROM aquila_sessions WHERE session_id = %s AND expires_at > NOW()",
                (session_id,),
            )
            .fetchone()
        )
        if not row or not row[0]:
            return []
        try:
            return messages_from_dict(json.loads(row[0]))
        except Exception:
            logger.warning(
                "store: failed to deserialise history for %s — starting fresh", session_id
            )
            return []

    # ── Delete ─────────────────────────────────────────────────────────────

    def delete_session(self, session_id: str, repo_id: str) -> None:
        self._live().execute(
            "DELETE FROM aquila_sessions WHERE session_id = %s",
            (session_id,),
        )

    def delete_all_repo_sessions(self, repo_id: str) -> None:
        """Remove every session belonging to *repo_id*."""
        self._live().execute(
            "DELETE FROM aquila_sessions WHERE repo_id = %s",
            (repo_id,),
        )


def create_store(postgres_url: str) -> SessionStore:
    """Connect to PostgreSQL and return a :class:`SessionStore`.

    Raises on connection failure so the caller can degrade gracefully.
    """
    return SessionStore(postgres_url)
