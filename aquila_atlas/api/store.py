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
        self._conn.execute(
            "ALTER TABLE aquila_sessions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''"
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
            INSERT INTO aquila_sessions (session_id, repo_id, user_id, meta, history, expires_at)
            VALUES (%s, %s, %s, %s, '[]', NOW() + %s::INTERVAL)
            ON CONFLICT (session_id) DO UPDATE
                SET meta       = EXCLUDED.meta,
                    repo_id    = EXCLUDED.repo_id,
                    user_id    = EXCLUDED.user_id,
                    expires_at = EXCLUDED.expires_at
            """,
            (session_id, meta.get("repo_id", ""), meta.get("user_id", ""), json.dumps(meta), _TTL),
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
        return json.loads(row[0])  # type: ignore[no-any-return]

    def list_repo_sessions(self, repo_id: str, user_id: str = "") -> list[dict[str, Any]]:
        """Return metadata for every non-expired session belonging to *repo_id*.

        When *user_id* is provided only sessions owned by that user are returned.
        """
        if user_id:
            rows = (
                self._live()
                .execute(
                    "SELECT meta FROM aquila_sessions"
                    " WHERE repo_id = %s AND user_id = %s AND expires_at > NOW()",
                    (repo_id, user_id),
                )
                .fetchall()
            )
        else:
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

    def delete_all_repo_sessions(self, repo_id: str) -> int:
        """Remove every session belonging to *repo_id*. Returns count deleted."""
        cur = self._live().execute(
            "DELETE FROM aquila_sessions WHERE repo_id = %s",
            (repo_id,),
        )
        return cur.rowcount or 0


def create_store(postgres_url: str) -> SessionStore:
    """Connect to PostgreSQL and return a :class:`SessionStore`.

    Raises on connection failure so the caller can degrade gracefully.
    """
    return SessionStore(postgres_url)


# ---------------------------------------------------------------------------
# DocStore — PostgreSQL-backed documentation persistence
# ---------------------------------------------------------------------------


class DocStore:
    """PostgreSQL-backed storage for generated documentation.

    Mirrors SessionStore design: synchronous psycopg3, single-row ops,
    safe to call from async FastAPI handlers. 30-day TTL, same as sessions.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_docs (
                job_id     TEXT PRIMARY KEY,
                repo_id    TEXT NOT NULL,
                scope      TEXT NOT NULL,
                style      TEXT NOT NULL,
                language   TEXT NOT NULL,
                files      TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_docs_repo_id ON aquila_docs (repo_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_docs_expires_at ON aquila_docs (expires_at)"
        )
        self._conn.execute(
            "ALTER TABLE aquila_docs ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''"
        )

    def _live(self) -> Any:
        import psycopg  # noqa: PLC0415

        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    def save_doc(
        self,
        job_id: str,
        repo_id: str,
        scope: str,
        style: str,
        language: str,
        files: dict[str, str],
        user_id: str = "",
    ) -> bool:
        """Persist generated docs. Returns True on success."""
        try:
            self._live().execute(
                """
                INSERT INTO aquila_docs (job_id, repo_id, user_id, scope, style, language, files,
                                         created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + %s::INTERVAL)
                ON CONFLICT (job_id) DO UPDATE
                    SET files      = EXCLUDED.files,
                        user_id    = EXCLUDED.user_id,
                        expires_at = EXCLUDED.expires_at
                """,
                (job_id, repo_id, user_id, scope, style, language, json.dumps(files), _TTL),
            )
            return True
        except Exception:
            logger.warning("DocStore.save_doc failed for job_id=%s", job_id, exc_info=True)
            return False

    def load_doc(self, job_id: str) -> dict[str, Any] | None:
        """Load a doc record by job_id. Returns dict with parsed files or None."""
        row = (
            self._live()
            .execute(
                """
                SELECT job_id, repo_id, scope, style, language, files, created_at
                FROM aquila_docs
                WHERE job_id = %s AND expires_at > NOW()
                """,
                (job_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "job_id": row[0],
            "repo_id": row[1],
            "scope": row[2],
            "style": row[3],
            "language": row[4],
            "files": json.loads(row[5]),
            "created_at": row[6].isoformat() if row[6] else None,
        }

    def list_repo_docs(self, repo_id: str, user_id: str = "") -> list[dict[str, Any]]:
        """Return metadata (no file content) for all non-expired docs in *repo_id*.

        When *user_id* is provided only docs owned by that user are returned.
        """
        if user_id:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, scope, style, language, created_at
                    FROM aquila_docs
                    WHERE repo_id = %s AND user_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id, user_id),
                )
                .fetchall()
            )
        else:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, scope, style, language, created_at
                    FROM aquila_docs
                    WHERE repo_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id,),
                )
                .fetchall()
            )
        return [
            {
                "job_id": row[0],
                "repo_id": row[1],
                "scope": row[2],
                "style": row[3],
                "language": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]

    def delete_all_repo_docs(self, repo_id: str) -> int:
        """Remove all doc records for *repo_id*. Returns count deleted."""
        cur = self._live().execute(
            "DELETE FROM aquila_docs WHERE repo_id = %s",
            (repo_id,),
        )
        return cur.rowcount or 0

    def delete_doc(self, repo_id: str, job_id: str) -> bool:
        """Delete a doc. Returns True if a row was removed."""
        result = (
            self._live()
            .execute(
                "DELETE FROM aquila_docs WHERE job_id = %s AND repo_id = %s RETURNING job_id",
                (job_id, repo_id),
            )
            .fetchone()
        )
        return result is not None


def create_doc_store(postgres_url: str) -> DocStore:
    """Connect to PostgreSQL and return a :class:`DocStore`."""
    return DocStore(postgres_url)


# ---------------------------------------------------------------------------
# TestStore — PostgreSQL-backed test-generation persistence
# ---------------------------------------------------------------------------


class TestStore:
    """PostgreSQL-backed storage for generated test scaffolds.

    Mirrors DocStore design: synchronous psycopg3, 30-day TTL.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_tests (
                job_id          TEXT PRIMARY KEY,
                repo_id         TEXT NOT NULL,
                scope           TEXT NOT NULL,
                language_filter TEXT NOT NULL DEFAULT '[]',
                files           TEXT NOT NULL DEFAULT '{}',
                file_statuses   TEXT NOT NULL DEFAULT '{}',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
            )
            """
        )
        # Migration: add file_statuses column to existing tables
        self._conn.execute(
            """
            ALTER TABLE aquila_tests
            ADD COLUMN IF NOT EXISTS file_statuses TEXT NOT NULL DEFAULT '{}'
            """
        )
        self._conn.execute(
            "ALTER TABLE aquila_tests ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_tests_repo_id ON aquila_tests (repo_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_tests_expires_at ON aquila_tests (expires_at)"
        )

    def _live(self) -> Any:
        import psycopg  # noqa: PLC0415

        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    def save_tests(
        self,
        job_id: str,
        repo_id: str,
        scope: str,
        language_filter: list[str] | None,
        files: dict[str, str],
        file_statuses: dict[str, str] | None = None,
        user_id: str = "",
    ) -> bool:
        """Persist generated tests. Returns True on success."""
        try:
            self._live().execute(
                """
                INSERT INTO aquila_tests
                    (job_id, repo_id, user_id, scope, language_filter, files, file_statuses,
                     created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + %s::INTERVAL)
                ON CONFLICT (job_id) DO UPDATE
                    SET files           = EXCLUDED.files,
                        file_statuses   = EXCLUDED.file_statuses,
                        user_id         = EXCLUDED.user_id,
                        expires_at      = EXCLUDED.expires_at
                """,
                (
                    job_id,
                    repo_id,
                    user_id,
                    scope,
                    json.dumps(language_filter or []),
                    json.dumps(files),
                    json.dumps(file_statuses or {}),
                    _TTL,
                ),
            )
            return True
        except Exception:
            logger.warning("TestStore.save_tests failed for job_id=%s", job_id, exc_info=True)
            return False

    def load_tests(self, job_id: str) -> dict[str, Any] | None:
        row = (
            self._live()
            .execute(
                """
                SELECT job_id, repo_id, scope, language_filter, files, file_statuses, created_at
                FROM aquila_tests
                WHERE job_id = %s AND expires_at > NOW()
                """,
                (job_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "job_id": row[0],
            "repo_id": row[1],
            "scope": row[2],
            "language_filter": json.loads(row[3]),
            "files": json.loads(row[4]),
            "file_statuses": json.loads(row[5]) if row[5] else {},
            "created_at": row[6].isoformat() if row[6] else None,
        }

    def list_repo_tests(self, repo_id: str, user_id: str = "") -> list[dict[str, Any]]:
        """Return metadata for all non-expired test sets in *repo_id*.

        When *user_id* is provided only test sets owned by that user are returned.
        """
        if user_id:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, scope, language_filter, created_at
                    FROM aquila_tests
                    WHERE repo_id = %s AND user_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id, user_id),
                )
                .fetchall()
            )
        else:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, scope, language_filter, created_at
                    FROM aquila_tests
                    WHERE repo_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id,),
                )
                .fetchall()
            )
        return [
            {
                "job_id": row[0],
                "repo_id": row[1],
                "scope": row[2],
                "language_filter": json.loads(row[3]),
                "created_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]

    def delete_tests(self, repo_id: str, job_id: str) -> bool:
        result = (
            self._live()
            .execute(
                "DELETE FROM aquila_tests WHERE job_id = %s AND repo_id = %s RETURNING job_id",
                (job_id, repo_id),
            )
            .fetchone()
        )
        return result is not None

    def delete_all_repo_tests(self, repo_id: str) -> int:
        cur = self._live().execute(
            "DELETE FROM aquila_tests WHERE repo_id = %s",
            (repo_id,),
        )
        return cur.rowcount or 0


def create_test_store(postgres_url: str) -> TestStore:
    """Connect to PostgreSQL and return a :class:`TestStore`."""
    return TestStore(postgres_url)


# ---------------------------------------------------------------------------
# SecurityStore — PostgreSQL-backed security scan persistence
# ---------------------------------------------------------------------------


class SecurityStore:
    """PostgreSQL-backed storage for security scan results.

    Mirrors DocStore/TestStore design: synchronous psycopg3, 30-day TTL.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aquila_security_scans (
                job_id          TEXT PRIMARY KEY,
                repo_id         TEXT NOT NULL,
                source          TEXT NOT NULL,
                findings        TEXT NOT NULL DEFAULT '[]',
                report          TEXT NOT NULL DEFAULT '',
                severity_counts TEXT NOT NULL DEFAULT '{}',
                tools_used      TEXT NOT NULL DEFAULT '[]',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
            )
            """
        )
        # Migration: add tools_used column to existing tables
        self._conn.execute(
            "ALTER TABLE aquila_security_scans"
            " ADD COLUMN IF NOT EXISTS tools_used TEXT NOT NULL DEFAULT '[]'"
        )
        self._conn.execute(
            "ALTER TABLE aquila_security_scans"
            " ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_security_repo_id"
            " ON aquila_security_scans (repo_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_aquila_security_expires_at"
            " ON aquila_security_scans (expires_at)"
        )

    def _live(self) -> Any:
        import psycopg  # noqa: PLC0415

        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    def save_scan(
        self,
        job_id: str,
        repo_id: str,
        source: str,
        findings: list[dict[str, Any]],
        report: str,
        severity_counts: dict[str, int],
        tools_used: list[str] | None = None,
        user_id: str = "",
    ) -> bool:
        try:
            self._live().execute(
                """
                INSERT INTO aquila_security_scans
                    (job_id, repo_id, user_id, source, findings, report, severity_counts,
                     tools_used, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + %s::INTERVAL)
                ON CONFLICT (job_id) DO UPDATE
                    SET findings        = EXCLUDED.findings,
                        report          = EXCLUDED.report,
                        severity_counts = EXCLUDED.severity_counts,
                        tools_used      = EXCLUDED.tools_used,
                        user_id         = EXCLUDED.user_id,
                        expires_at      = EXCLUDED.expires_at
                """,
                (
                    job_id,
                    repo_id,
                    user_id,
                    source,
                    json.dumps(findings),
                    report,
                    json.dumps(severity_counts),
                    json.dumps(tools_used or []),
                    _TTL,
                ),
            )
            return True
        except Exception:
            logger.warning("SecurityStore.save_scan failed for job_id=%s", job_id, exc_info=True)
            return False

    def load_scan(self, job_id: str) -> dict[str, Any] | None:
        row = (
            self._live()
            .execute(
                """
                SELECT job_id, repo_id, source, findings, report,
                       severity_counts, tools_used, created_at
                FROM aquila_security_scans
                WHERE job_id = %s AND expires_at > NOW()
                """,
                (job_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "job_id": row[0],
            "repo_id": row[1],
            "source": row[2],
            "findings": json.loads(row[3]),
            "report": row[4],
            "severity_counts": json.loads(row[5]),
            "tools_used": json.loads(row[6]) if row[6] else [],
            "created_at": row[7].isoformat() if row[7] else None,
        }

    def list_repo_scans(self, repo_id: str, user_id: str = "") -> list[dict[str, Any]]:
        """Return metadata for all non-expired scans in *repo_id*.

        When *user_id* is provided only scans owned by that user are returned.
        """
        if user_id:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, source, severity_counts, created_at
                    FROM aquila_security_scans
                    WHERE repo_id = %s AND user_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id, user_id),
                )
                .fetchall()
            )
        else:
            rows = (
                self._live()
                .execute(
                    """
                    SELECT job_id, repo_id, source, severity_counts, created_at
                    FROM aquila_security_scans
                    WHERE repo_id = %s AND expires_at > NOW()
                    ORDER BY created_at DESC
                    """,
                    (repo_id,),
                )
                .fetchall()
            )
        return [
            {
                "job_id": row[0],
                "repo_id": row[1],
                "source": row[2],
                "severity_counts": json.loads(row[3]),
                "created_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]

    def delete_scan(self, repo_id: str, job_id: str) -> bool:
        result = (
            self._live()
            .execute(
                "DELETE FROM aquila_security_scans"
                " WHERE job_id = %s AND repo_id = %s RETURNING job_id",
                (job_id, repo_id),
            )
            .fetchone()
        )
        return result is not None

    def delete_all_repo_scans(self, repo_id: str) -> int:
        cur = self._live().execute(
            "DELETE FROM aquila_security_scans WHERE repo_id = %s",
            (repo_id,),
        )
        return cur.rowcount or 0


def create_security_store(postgres_url: str) -> SecurityStore:
    """Connect to PostgreSQL and return a :class:`SecurityStore`."""
    return SecurityStore(postgres_url)
