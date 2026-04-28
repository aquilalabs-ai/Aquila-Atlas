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
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from aquila_atlas.api.deps import Auth, CurrentUser, Svc  # noqa: TC001
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

_valid_scopes = {
    "architecture",
    "per_module",
    "per_file",
    "subsystem",
    "flows",
    "user_guide",
    "developer_guide",
}


def _uid(user: dict | None) -> str:  # type: ignore[type-arg]
    return user["id"] if user is not None else ""


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
    user_id: str = ""


_doc_jobs: dict[str, DocJobRecord] = {}

_SCOPE_LABELS: dict[str, str] = {
    "architecture": "Architecture",
    "per_module": "Per Module",
    "per_file": "Per File",
    "subsystem": "Subsystem",
    "flows": "Flows",
}
_STYLE_LABELS: dict[str, str] = {
    "technical": "Technical",
    "functional": "Functional",
}
_LANG_LABELS: dict[str, str] = {
    "en": "EN",
    "fr": "FR",
    "es": "ES",
    "de": "DE",
    "zh": "ZH",
    "ja": "JA",
    "pt": "PT",
    "ar": "AR",
}

_PDF_SCRIPT = (
    Path(__file__).parent.parent.parent.parent / "frontend" / "scripts" / "generate-pdf.cjs"
)


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
    from aquila_atlas.reasoning.docs_generator import (  # noqa: PLC0415
        GenerationCancelled,
        generate_docs,
    )

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
            user_id=record.user_id,
        )


async def _run_doc_job(job_id: str, svc: object, doc_store: object) -> None:
    record = _doc_jobs.get(job_id)
    if record is None:
        return
    record.status = "running"
    loop = asyncio.get_running_loop()
    try:
        files = await loop.run_in_executor(None, _sync_generate, record, svc)
        record.files = files
        record.status = "done"
        _persist_doc(record, doc_store)
        record.files = {}  # free bulk content; metadata kept for polling
    except Exception as exc:
        logger.exception("Doc job %s failed", job_id)
        record.status = "failed"
        record.error = str(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_doc_files(
    job_id: str, repo_id: str, request: Request
) -> tuple[dict[str, str], DocJobRecord | None]:
    """Return (files, record) from memory or DB; files is empty if not found/ready."""
    record = _doc_jobs.get(job_id)
    if (
        record is not None
        and record.repo_id == repo_id
        and record.status == "done"
        and record.files
    ):
        return record.files, record
    # If record exists but files were cleared after DB persist, fall through to DB for content
    doc_store = getattr(request.app.state, "doc_store", None)
    if doc_store is not None:
        from aquila_atlas.api.store import DocStore  # noqa: PLC0415

        if isinstance(doc_store, DocStore):
            row = doc_store.load_doc(job_id)
            if row is not None and row["repo_id"] == repo_id:
                return row["files"], record
    return {}, None


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
    user: CurrentUser,
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
        user_id=_uid(user),
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
    user: CurrentUser,
) -> DocListResponse:
    doc_store = getattr(request.app.state, "doc_store", None)
    if doc_store is None:
        return DocListResponse(repo_id=repo_id, docs=[], total=0)
    from aquila_atlas.api.store import DocStore  # noqa: PLC0415

    if not isinstance(doc_store, DocStore):
        return DocListResponse(repo_id=repo_id, docs=[], total=0)
    uid = _uid(user)
    rows = doc_store.list_repo_docs(repo_id, user_id=uid)
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
        if record.files:
            return DocContentResponse(
                job_id=record.job_id,
                repo_id=record.repo_id,
                scope=record.scope,
                style=record.style,
                language=record.language,
                files=record.files,
            )
        # Files were cleared from memory after DB persist; fall through to DB

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
    files, record = _resolve_doc_files(job_id, repo_id, request)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documentation not found or not ready"
        )

    scope = record.scope if record else "docs"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            zf.writestr(fname, content)
    buf.seek(0)

    filename = f"{repo_id}-docs-{scope}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/docs/{job_id}/download-pdf",
    summary="Download documentation as a PDF",
)
async def download_doc_pdf(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> StreamingResponse:
    files, record = _resolve_doc_files(job_id, repo_id, request)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documentation not found or not ready",
        )

    scope = record.scope if record else "docs"
    style = record.style if record else "technical"
    language = record.language if record else "en"

    scope_label = _SCOPE_LABELS.get(scope, scope.title())
    style_label = _STYLE_LABELS.get(style, style.title())
    lang_label = _LANG_LABELS.get(language, language.upper())

    title_block = (
        f"# Documentation: {scope_label} — {lang_label} — {style_label}\n\n"
        f"**Repository:** `{repo_id}`\n\n"
        f"---"
    )

    parts: list[str] = [title_block]
    for filename, content in files.items():
        parts.append(f"## `{filename}`\n\n{content}")
    combined = "\n\n---\n\n".join(parts)

    node_bin = shutil.which("node")
    if node_bin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Node.js not found — required for PDF generation",
        )
    if not _PDF_SCRIPT.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation script not found — run `npm install` in the frontend directory",
        )

    loop = asyncio.get_running_loop()

    def _run() -> bytes:
        result = subprocess.run(
            [node_bin, str(_PDF_SCRIPT)],
            input=combined.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(err or "PDF generation script exited with non-zero status")
        return result.stdout

    try:
        pdf_bytes = await loop.run_in_executor(None, _run)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PDF generation timed out",
        ) from exc
    except RuntimeError as exc:
        logger.exception("PDF generation failed for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF generation failed: {exc}",
        ) from exc

    filename = f"{repo_id}-docs-{scope}-{language}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
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
