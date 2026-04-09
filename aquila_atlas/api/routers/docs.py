"""Documentation generation router.

Endpoints
---------
POST   /repos/{repo_id}/docs/generate          — submit async doc job
GET    /repos/{repo_id}/docs/jobs/{job_id}      — poll job status + progress
GET    /repos/{repo_id}/docs                    — list saved docs (metadata)
GET    /repos/{repo_id}/docs/{job_id}           — get doc content (memory or DB)
GET    /repos/{repo_id}/docs/{job_id}/download-zip — stream ZIP of all files
DELETE /repos/{repo_id}/docs/{job_id}           — delete from DB
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    DocContentResponse,
    DocDeleteResponse,
    DocGenRequest,
    DocGenResponse,
    DocJobStatus,
    DocListResponse,
    DocMetadata,
)

logger = logging.getLogger("aquila.api.docs")

router = APIRouter(prefix="/repos/{repo_id}", tags=["Documentation"])

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

DocJobStatusLiteral = Literal["queued", "running", "done", "failed"]

_valid_scopes = {"architecture", "per_module", "per_file", "subsystem", "flows"}


@dataclass
class DocJobRecord:
    job_id: str
    repo_id: str
    scope: str
    style: str
    language: str
    status: DocJobStatusLiteral = "queued"
    files: dict[str, str] = field(default_factory=dict)
    completed: int = 0
    total: int = 0
    current_target: str | None = None
    error: str | None = None
    cancelled: bool = False
    exclude_extensions: list[str] | None = None


_doc_jobs: dict[str, DocJobRecord] = {}


# ---------------------------------------------------------------------------
# DocStore dependency
# ---------------------------------------------------------------------------


def _get_doc_store(request: Request) -> Any:
    return getattr(request.app.state, "doc_store", None)


DocStoreOrNone = Annotated[object, Depends(_get_doc_store)]


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------


def _sync_generate(record: DocJobRecord, svc: object) -> dict[str, str]:
    from aquila_atlas.reasoning.docs_generator import GenerationCancelled, generate_docs  # noqa: PLC0415

    def progress(completed: int, total: int, current_target: str | None) -> None:
        if record.cancelled:
            raise GenerationCancelled
        record.completed = completed
        record.total = total
        record.current_target = current_target

    try:
        return generate_docs(
            svc=svc,  # type: ignore[arg-type]
            repo_id=record.repo_id,
            scope=record.scope,  # type: ignore[arg-type]
            style=record.style,
            language=record.language,
            exclude_extensions=record.exclude_extensions,
            progress_callback=progress,
        )
    except GenerationCancelled as exc:
        # Return whatever files were completed before cancellation
        return exc.partial


def _persist_doc(record: DocJobRecord, doc_store: object) -> None:
    """Save completed (or partial) doc files to the database if available."""
    if not record.files or doc_store is None:
        return
    from aquila_atlas.api.store import DocStore  # noqa: PLC0415

    if isinstance(doc_store, DocStore):
        doc_store.save_doc(
            job_id=record.job_id,
            repo_id=record.repo_id,
            scope=record.scope,
            style=record.style,
            language=record.language,
            files=record.files,
        )


async def _run_doc_job(job_id: str, svc: object, doc_store: object) -> None:
    record = _doc_jobs.get(job_id)
    if record is None:
        return
    record.status = "running"
    loop = asyncio.get_event_loop()
    try:
        files = await loop.run_in_executor(None, _sync_generate, record, svc)
        record.files = files
        record.status = "done"
        _persist_doc(record, doc_store)
    except Exception as exc:
        logger.exception("Doc job %s failed", job_id)
        record.status = "failed"
        record.error = str(exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/docs/generate",
    response_model=DocGenResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit documentation generation job",
)
async def generate_docs_endpoint(
    repo_id: str,
    body: DocGenRequest,
    request: Request,
    svc: Svc,
    _auth: Auth,
) -> DocGenResponse:
    if body.scope not in _valid_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid scope '{body.scope}'. Valid: {sorted(_valid_scopes)}",
        )
    job_id = str(uuid.uuid4())
    record = DocJobRecord(
        job_id=job_id,
        repo_id=repo_id,
        scope=body.scope,
        style=body.style,
        language=body.language,
        exclude_extensions=body.exclude_extensions,
    )
    _doc_jobs[job_id] = record
    doc_store = getattr(request.app.state, "doc_store", None)
    asyncio.create_task(_run_doc_job(job_id, svc, doc_store))
    return DocGenResponse(job_id=job_id, repo_id=repo_id, status="queued")


@router.get(
    "/docs/jobs/{job_id}",
    response_model=DocJobStatus,
    summary="Poll documentation job status",
)
async def get_doc_job_status(
    repo_id: str,
    job_id: str,
    _auth: Auth,
) -> DocJobStatus:
    record = _doc_jobs.get(job_id)
    if record is None or record.repo_id != repo_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return DocJobStatus(
        job_id=record.job_id,
        repo_id=record.repo_id,
        scope=record.scope,
        style=record.style,
        language=record.language,
        status=record.status,
        completed=record.completed,
        total=record.total,
        current_target=record.current_target,
        error=record.error,
        files=sorted(record.files.keys()) if record.status == "done" else [],
    )


@router.get(
    "/docs",
    response_model=DocListResponse,
    summary="List saved documentation for a repo",
)
async def list_repo_docs(
    repo_id: str,
    request: Request,
    _auth: Auth,
) -> DocListResponse:
    doc_store = getattr(request.app.state, "doc_store", None)
    if doc_store is None:
        return DocListResponse(repo_id=repo_id, docs=[], total=0)
    from aquila_atlas.api.store import DocStore  # noqa: PLC0415

    if not isinstance(doc_store, DocStore):
        return DocListResponse(repo_id=repo_id, docs=[], total=0)
    rows = doc_store.list_repo_docs(repo_id)
    docs = [DocMetadata(**row) for row in rows]
    return DocListResponse(repo_id=repo_id, docs=docs, total=len(docs))


@router.get(
    "/docs/{job_id}",
    response_model=DocContentResponse,
    summary="Get documentation content (memory or DB)",
)
async def get_doc_content(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> DocContentResponse:
    # Check in-memory first
    record = _doc_jobs.get(job_id)
    if record is not None and record.repo_id == repo_id:
        if record.status != "done":
            raise HTTPException(
                status_code=status.HTTP_425_TOO_EARLY,
                detail=f"Job status is '{record.status}', not done yet",
            )
        return DocContentResponse(
            job_id=record.job_id,
            repo_id=record.repo_id,
            scope=record.scope,
            style=record.style,
            language=record.language,
            files=record.files,
        )

    # Fallback to DB
    doc_store = getattr(request.app.state, "doc_store", None)
    if doc_store is not None:
        from aquila_atlas.api.store import DocStore  # noqa: PLC0415

        if isinstance(doc_store, DocStore):
            row = doc_store.load_doc(job_id)
            if row is not None and row["repo_id"] == repo_id:
                return DocContentResponse(
                    job_id=row["job_id"],
                    repo_id=row["repo_id"],
                    scope=row["scope"],
                    style=row["style"],
                    language=row["language"],
                    files=row["files"],
                )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documentation not found")


@router.get(
    "/docs/{job_id}/download-zip",
    summary="Download all documentation files as a ZIP archive",
)
async def download_doc_zip(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> StreamingResponse:
    # Resolve files from memory or DB
    files: dict[str, str] = {}
    record = _doc_jobs.get(job_id)
    if record is not None and record.repo_id == repo_id and record.status == "done":
        files = record.files
    else:
        doc_store = getattr(request.app.state, "doc_store", None)
        if doc_store is not None:
            from aquila_atlas.api.store import DocStore  # noqa: PLC0415

            if isinstance(doc_store, DocStore):
                row = doc_store.load_doc(job_id)
                if row is not None and row["repo_id"] == repo_id:
                    files = row["files"]

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documentation not found or not ready"
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    buf.seek(0)

    scope = record.scope if record else "docs"
    filename = f"{repo_id}-docs-{scope}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/docs/jobs/{job_id}/cancel",
    response_model=DocJobStatus,
    summary="Cancel a running documentation job",
)
async def cancel_doc_job(
    repo_id: str,
    job_id: str,
    _auth: Auth,
) -> DocJobStatus:
    record = _doc_jobs.get(job_id)
    if record is None or record.repo_id != repo_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if record.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is already '{record.status}', cannot cancel",
        )
    record.cancelled = True
    return DocJobStatus(
        job_id=record.job_id,
        repo_id=record.repo_id,
        scope=record.scope,
        style=record.style,
        language=record.language,
        status=record.status,
        completed=record.completed,
        total=record.total,
        current_target=record.current_target,
        error=record.error,
        files=[],
    )


@router.delete(
    "/docs/{job_id}",
    response_model=DocDeleteResponse,
    summary="Delete saved documentation",
)
async def delete_doc(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> DocDeleteResponse:
    # Remove from memory
    if job_id in _doc_jobs and _doc_jobs[job_id].repo_id == repo_id:
        del _doc_jobs[job_id]

    # Remove from DB
    doc_store = getattr(request.app.state, "doc_store", None)
    deleted_from_db = False
    if doc_store is not None:
        from aquila_atlas.api.store import DocStore  # noqa: PLC0415

        if isinstance(doc_store, DocStore):
            deleted_from_db = doc_store.delete_doc(repo_id, job_id)

    return DocDeleteResponse(
        success=True,
        job_id=job_id,
        message="Deleted from database" if deleted_from_db else "Removed from memory",
    )
