"""Valkey/Redis-backed job registry for ingestion and resync jobs.

Jobs are stored as Redis hashes with a 7-day TTL. A per-repo list tracks the
insertion order of job IDs so ``latest_for_repo`` can return the most recent
one in O(1). Zip payloads are stored as raw bytes under a separate key with a
shorter 2-hour TTL and deleted automatically after ingestion completes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aquila_atlas.api.tasks import JobRecord, JobStatusLiteral

_JOB_TTL = 86400 * 7  # 7 days
_ZIP_TTL = 3600 * 2  # 2 hours


class JobStore:
    """Valkey/Redis-backed persistent job registry.

    Uses two Redis connection instances: one with ``decode_responses=True`` for
    string hash fields, and one with ``decode_responses=False`` for binary zip
    payloads.
    """

    def __init__(self, url: str) -> None:
        import redis  # noqa: PLC0415

        self._r: Any = redis.from_url(url, decode_responses=True)
        self._rb: Any = redis.from_url(url, decode_responses=False)

    # ── Key helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _jk(job_id: str) -> str:
        return f"aquila:job:{job_id}"

    @staticmethod
    def _rk(repo_id: str) -> str:
        return f"aquila:repo_jobs:{repo_id}"

    @staticmethod
    def _zk(job_id: str) -> str:
        return f"aquila:zip:{job_id}"

    # ── Serialisation ──────────────────────────────────────────────────────

    @staticmethod
    def _to_hash(record: JobRecord) -> dict[str, str]:
        return {
            "job_id": record.job_id,
            "repo_id": record.repo_id,
            "path": record.path,
            "source_type": record.source_type,
            "github_token": record.github_token,
            "status": record.status,
            "files": "" if record.files is None else str(record.files),
            "chunks": "" if record.chunks is None else str(record.chunks),
            "error": record.error or "",
            "ingest_type": record.ingest_type,
            "changed_files": "" if record.changed_files is None else str(record.changed_files),
            "old_commit_sha": record.old_commit_sha or "",
            "new_commit_sha": record.new_commit_sha or "",
        }

    @staticmethod
    def _from_hash(data: dict[str, str]) -> JobRecord:
        from aquila_atlas.api.tasks import JobRecord  # noqa: PLC0415

        def _opt_int(v: str) -> int | None:
            return int(v) if v else None

        def _opt_str(v: str) -> str | None:
            return v or None

        return JobRecord(
            job_id=data["job_id"],
            repo_id=data["repo_id"],
            path=data["path"],
            source_type=data.get("source_type", "local"),
            github_token=data.get("github_token", ""),
            status=data.get("status", "queued"),  # type: ignore[arg-type]
            files=_opt_int(data.get("files", "")),
            chunks=_opt_int(data.get("chunks", "")),
            error=_opt_str(data.get("error", "")),
            ingest_type=data.get("ingest_type", "full"),
            changed_files=_opt_int(data.get("changed_files", "")),
            old_commit_sha=_opt_str(data.get("old_commit_sha", "")),
            new_commit_sha=_opt_str(data.get("new_commit_sha", "")),
        )

    # ── Write operations ───────────────────────────────────────────────────

    def save(self, record: JobRecord) -> None:
        """Persist a new or updated record (including zip data if present)."""
        key = self._jk(record.job_id)
        self._r.hset(key, mapping=self._to_hash(record))
        self._r.expire(key, _JOB_TTL)

        repo_key = self._rk(record.repo_id)
        self._r.rpush(repo_key, record.job_id)
        self._r.expire(repo_key, _JOB_TTL)

        if record.zip_data is not None:
            self._rb.set(self._zk(record.job_id), record.zip_data, ex=_ZIP_TTL)

    def update(self, record: JobRecord) -> None:
        """Overwrite all mutable fields on an existing record.

        Also removes the zip key when ``record.zip_data`` is ``None``,
        signalling that ingestion has consumed and cleared the payload.
        """
        key = self._jk(record.job_id)
        self._r.hset(key, mapping=self._to_hash(record))
        if record.zip_data is None:
            self._rb.delete(self._zk(record.job_id))

    def update_status(self, job_id: str, job_status: JobStatusLiteral) -> None:
        """Update only the status field — cheapest write path for live polling."""
        self._r.hset(self._jk(job_id), "status", job_status)

    # ── Read operations ────────────────────────────────────────────────────

    def get(self, job_id: str) -> JobRecord | None:
        data: dict[str, str] = self._r.hgetall(self._jk(job_id))
        if not data:
            return None
        record = self._from_hash(data)
        zip_bytes: bytes | None = self._rb.get(self._zk(job_id))
        if zip_bytes:
            record.zip_data = zip_bytes
        return record

    def latest_for_repo(self, repo_id: str) -> JobRecord | None:
        """Return the most recently submitted job for *repo_id*, or ``None``."""
        job_id: str | None = self._r.lindex(self._rk(repo_id), -1)
        if not job_id:
            return None
        return self.get(job_id)

    def ping(self) -> bool:
        """Return True if the Valkey server is reachable."""
        try:
            return bool(self._r.ping())
        except Exception:
            return False
