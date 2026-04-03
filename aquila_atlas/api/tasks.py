"""Background ingestion jobs — asyncio-based task queue (MVP in-memory store)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

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


# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

_jobs: dict[str, JobRecord] = {}


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
    _jobs[job_id] = record
    return record


def get_job(job_id: str) -> JobRecord | None:
    return _jobs.get(job_id)


def latest_job_for_repo(repo_id: str) -> JobRecord | None:
    """Return the most recently created job for a given repo_id."""
    matches = [j for j in _jobs.values() if j.repo_id == repo_id]
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Ingestion runner
# ---------------------------------------------------------------------------


async def run_ingestion(job_id: str) -> None:
    """Run the full ingestion pipeline for *job_id* in a thread-pool executor."""
    record = _jobs.get(job_id)
    if record is None:
        return

    record.status = "running"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_ingest, record)
        record.status = "done"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = str(exc)


def _build_loader(record: JobRecord) -> object:
    """Build the appropriate source loader based on source_type."""
    from aquila_atlas.ingestion import LocalFolderLoader  # noqa: PLC0415
    from aquila_atlas.ingestion.sources import GitHubLoader, ZipLoader  # noqa: PLC0415

    if record.source_type == "github":
        return GitHubLoader(url=record.path, token=record.github_token)
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

    svc = get_knowledge_service()
    svc.graph.ingest(
        repo_id=record.repo_id,
        label=loader.label(),
        entities=all_entities,
        commit_sha=None,
    )
    svc.ingest_chunks(chunks, repo_id=record.repo_id)
    # Free zip data after ingestion to release memory
    record.zip_data = None
