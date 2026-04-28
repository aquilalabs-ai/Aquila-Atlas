"""Background ingestion jobs — Valkey-backed job store with in-memory cache.

Job lifecycle
-------------
1. ``create_job`` / ``create_resync_job`` — allocate a ``JobRecord`` and
   persist it (status: ``queued``).
2. ``run_ingestion`` / ``run_resync`` — flip status to ``running``, delegate
   the blocking work to a thread-pool executor, then persist the final state.
3. ``get_job`` / ``latest_job_for_repo`` — check the local cache first;
   fall back to Valkey so jobs created by another worker (or before a restart)
   are still visible.

When Valkey is unavailable the module falls back silently to the in-process
``_jobs`` dict — identical behaviour to the original implementation.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from aquila_atlas.api.job_store import JobStore

JobStatusLiteral = Literal["queued", "running", "done", "failed"]


# ---------------------------------------------------------------------------
# Job record
# ---------------------------------------------------------------------------


@dataclass
class JobRecord:
    job_id: str
    repo_id: str
    path: str
    source_type: str = "local"
    github_token: str = ""
    zip_data: bytes | None = None
    status: JobStatusLiteral = "queued"
    files: int | None = None
    chunks: int | None = None
    error: str | None = None
    # Resync-specific fields
    ingest_type: str = "full"  # "full" | "resync"
    changed_files: int | None = None  # number of files re-indexed (resync only)
    old_commit_sha: str | None = None
    new_commit_sha: str | None = None


# ---------------------------------------------------------------------------
# Storage — Valkey-backed with in-memory fallback
# ---------------------------------------------------------------------------

_jobs: dict[str, JobRecord] = {}
_store: JobStore | None = None


def init_job_store(url: str) -> None:
    """Initialise the Valkey job store.  Called once from the API lifespan."""
    global _store
    from aquila_atlas.api.job_store import JobStore  # noqa: PLC0415

    _store = JobStore(url)


def _save(record: JobRecord) -> None:
    """Write-through: cache locally and persist to Valkey."""
    _jobs[record.job_id] = record
    if _store is not None:
        _store.save(record)


def _update(record: JobRecord) -> None:
    """Persist all mutable fields of an existing record to Valkey."""
    if _store is not None:
        _store.update(record)


def _set_status(record: JobRecord, st: JobStatusLiteral) -> None:
    """Update status in-place and push the change to Valkey immediately."""
    record.status = st
    if _store is not None:
        _store.update_status(record.job_id, st)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_job(
    repo_id: str,
    path: str,
    source_type: str = "local",
    github_token: str = "",
    zip_data: bytes | None = None,
) -> JobRecord:
    """Register a new ingestion job and return its record."""
    job_id = str(uuid.uuid4())
    record = JobRecord(
        job_id=job_id,
        repo_id=repo_id,
        path=path,
        source_type=source_type,
        github_token=github_token,
        zip_data=zip_data,
    )
    _save(record)
    return record


def create_resync_job(
    repo_id: str,
    path: str,
    source_type: str = "local",
    github_token: str = "",
) -> JobRecord:
    """Register a resync job and return its record."""
    job_id = str(uuid.uuid4())
    record = JobRecord(
        job_id=job_id,
        repo_id=repo_id,
        path=path,
        source_type=source_type,
        github_token=github_token,
        ingest_type="resync",
    )
    _save(record)
    return record


def get_job(job_id: str) -> JobRecord | None:
    """Return a job record by ID.

    Checks the local in-memory cache first.  Falls back to Valkey so that jobs
    created by a different worker process (or before a server restart) are
    still visible.
    """
    if job_id in _jobs:
        return _jobs[job_id]
    if _store is not None:
        record = _store.get(job_id)
        if record is not None:
            _jobs[job_id] = record  # warm the local cache
        return record
    return None


def latest_job_for_repo(repo_id: str) -> JobRecord | None:
    """Return the most recently created job for *repo_id*.

    Delegates to Valkey when available (correct across workers/restarts);
    falls back to scanning the local dict.
    """
    if _store is not None:
        return _store.latest_for_repo(repo_id)
    matches = [j for j in _jobs.values() if j.repo_id == repo_id]
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Ingestion runner
# ---------------------------------------------------------------------------


async def run_ingestion(job_id: str) -> None:
    """Run the full ingestion pipeline for *job_id* in a thread-pool executor."""
    record = get_job(job_id)
    if record is None:
        return

    _set_status(record, "running")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_ingest, record)
        record.status = "done"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = str(exc)
    finally:
        _update(record)


def _build_loader(record: JobRecord) -> Any:
    """Build the appropriate source loader based on source_type."""
    from aquila_atlas.ingestion import LocalFolderLoader  # noqa: PLC0415
    from aquila_atlas.ingestion.sources import (  # noqa: PLC0415
        GitCloneLoader,
        GiteaLoader,
        GitHubLoader,
        GitLabLoader,
        ZipLoader,
    )

    if record.source_type == "github":
        return GitHubLoader(url=record.path, token=record.github_token)
    if record.source_type == "gitlab":
        return GitLabLoader(url=record.path, token=record.github_token)
    if record.source_type == "gitea":
        return GiteaLoader(url=record.path, token=record.github_token)
    if record.source_type == "git":
        return GitCloneLoader(url=record.path, token=record.github_token)
    if record.source_type == "zip":
        if record.zip_data:
            return ZipLoader(record.zip_data)
        return ZipLoader(record.path)
    return LocalFolderLoader(record.path)


def _sync_ingest(record: JobRecord) -> None:
    """Blocking ingestion pipeline — runs in a thread-pool executor."""
    from aquila_atlas.ingestion import chunk_files, parse  # noqa: PLC0415
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415

    loader = _build_loader(record)
    files = list(loader.load())
    record.files = len(files)

    all_entities = []
    for f in files:
        all_entities.extend(parse(f))

    chunks = list(chunk_files(files))
    record.chunks = len(chunks)

    # Capture commit SHA if the loader supports it
    commit_sha: str | None = None
    if hasattr(loader, "head_sha"):
        commit_sha = loader.head_sha()

    svc = get_knowledge_service()
    svc.graph.ingest(
        repo_id=record.repo_id,
        label=loader.label(),
        entities=all_entities,
        commit_sha=commit_sha,
        source_type=record.source_type,
        has_token=bool(record.github_token),
    )
    svc.ingest_chunks(chunks, repo_id=record.repo_id)
    # Free zip payload after ingestion — triggers Valkey key deletion in _update
    record.zip_data = None


async def run_resync(job_id: str) -> None:
    """Run the incremental resync pipeline for *job_id* in a thread-pool executor."""
    record = get_job(job_id)
    if record is None:
        return

    _set_status(record, "running")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_resync, record)
        record.status = "done"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = str(exc)
    finally:
        _update(record)


def _sync_resync(record: JobRecord) -> None:
    """Blocking resync pipeline — detects changed files and re-embeds them."""
    from aquila_atlas.ingestion import chunk_files, parse  # noqa: PLC0415
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415

    if record.source_type == "zip":
        raise ValueError("Resync is not supported for zip sources — re-ingest instead.")

    svc = get_knowledge_service()
    loader = _build_loader(record)

    # ── Detect HEAD SHA ──────────────────────────────────────────────────────
    if not hasattr(loader, "head_sha"):
        raise ValueError(f"Source type '{record.source_type}' does not support resync.")

    new_sha: str | None = loader.head_sha()

    if new_sha is None:
        import shutil as _shutil  # noqa: PLC0415

        git_missing = _shutil.which("git") is None
        if git_missing:
            raise ValueError(
                "git is not installed or not on PATH — cannot determine the current commit. "
                "Install git and ensure it is accessible to the server process."
            )
        raise ValueError(
            "This folder is not a git repository — resync requires git history to detect changes. "
            "If you want to refresh the index, run a full re-ingest instead."
        )

    old_sha = svc.get_repo_commit_sha(record.repo_id)
    record.old_commit_sha = old_sha
    record.new_commit_sha = new_sha

    if old_sha is None:
        raise ValueError(
            "No commit SHA is stored for this repo. This usually means it was ingested before "
            "resync support was added, or it was not a git repository at ingest time. "
            "Re-ingest the repo once to record the baseline commit SHA."
        )

    if old_sha == new_sha:
        # Nothing changed — mark done with 0 files
        record.changed_files = 0
        record.files = 0
        record.chunks = 0
        return

    # ── Get diff ─────────────────────────────────────────────────────────────
    changed_paths = loader.diff_files(old_sha, new_sha)
    if not changed_paths:
        record.changed_files = 0
        record.files = 0
        record.chunks = 0
        # Still update the SHA so future resyncs use the new base
        svc.graph.ingest(
            repo_id=record.repo_id,
            label=loader.label(),
            entities=[],
            commit_sha=new_sha,
            source_type=record.source_type,
            has_token=bool(record.github_token),
        )
        return

    record.changed_files = len(changed_paths)

    # ── Delete stale data for changed files ──────────────────────────────────
    svc.delete_files(record.repo_id, changed_paths)

    # ── Load, parse, chunk, and re-index only changed files ──────────────────
    changed_files = list(loader.load_paths(changed_paths))
    record.files = len(changed_files)

    all_entities = []
    for f in changed_files:
        all_entities.extend(parse(f))

    chunks = list(chunk_files(changed_files))
    record.chunks = len(chunks)

    # Re-ingest graph nodes for changed files + update commit SHA
    svc.graph.ingest(
        repo_id=record.repo_id,
        label=loader.label(),
        entities=all_entities,
        commit_sha=new_sha,
        source_type=record.source_type,
        has_token=bool(record.github_token),
    )
    if chunks:
        svc.ingest_chunks(chunks, repo_id=record.repo_id)
