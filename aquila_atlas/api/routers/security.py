"""Security scanning router.

Endpoints
---------
POST   /repos/{repo_id}/security/scan           — submit async scan job
GET    /repos/{repo_id}/security/jobs/{job_id}  — poll job status
GET    /repos/{repo_id}/security/scans          — list saved scans (metadata)
GET    /repos/{repo_id}/security/scans/{job_id} — get scan report + findings
DELETE /repos/{repo_id}/security/scans/{job_id} — delete scan record
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    FindingSummary,
    SecurityDeleteResponse,
    SecurityReport,
    SecurityScanJob,
    SecurityScanListResponse,
    SecurityScanMeta,
    SecurityScanRequest,
    SecurityScanResponse,
)

logger = logging.getLogger("aquila.api.security")

router = APIRouter(prefix="/repos/{repo_id}", tags=["Security"])

ScanStatusLiteral = Literal["queued", "running", "done", "failed"]

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------


@dataclass
class SecurityJobRecord:
    job_id: str
    repo_id: str
    source: str
    status: ScanStatusLiteral = "queued"
    completed: int = 0
    total: int = 4
    current_phase: str | None = None
    error: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    report: str = ""
    severity_counts: dict[str, int] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    cancelled: bool = False
    # Scan options
    token: str = ""
    branch: str = ""
    semgrep_config: str = "auto"
    run_llm_triage: bool = True


_security_jobs: dict[str, SecurityJobRecord] = {}


# ---------------------------------------------------------------------------
# SecurityStore dependency
# ---------------------------------------------------------------------------


def _get_security_store(request: Request) -> Any:
    return getattr(request.app.state, "security_store", None)


SecurityStoreOrNone = Annotated[object, Depends(_get_security_store)]


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------


def _sync_scan(record: SecurityJobRecord, svc: object) -> None:
    from aquila_atlas.security.scanner import scan  # noqa: PLC0415

    def progress(completed: int, total: int, label: str | None) -> None:
        record.completed = completed
        record.total = total
        record.current_phase = label

    result = scan(
        source=record.source,
        repo_id=record.repo_id,
        svc=svc,  # type: ignore[arg-type]
        token=record.token,
        branch=record.branch,
        semgrep_config=record.semgrep_config,
        run_llm_triage=record.run_llm_triage,
        progress_callback=progress,
    )
    record.findings = [f.to_dict() for f in result.findings]
    record.report = result.report
    record.severity_counts = result.stats
    record.tools_used = result.tools_used


def _persist_scan(record: SecurityJobRecord, security_store: object) -> None:
    if security_store is None:
        return
    from aquila_atlas.api.store import SecurityStore  # noqa: PLC0415

    if isinstance(security_store, SecurityStore):
        security_store.save_scan(
            job_id=record.job_id,
            repo_id=record.repo_id,
            source=record.source,
            findings=record.findings,
            report=record.report,
            severity_counts=record.severity_counts,
            tools_used=record.tools_used,
        )


async def _run_security_job(job_id: str, svc: object, security_store: object) -> None:
    record = _security_jobs.get(job_id)
    if record is None:
        return
    record.status = "running"
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _sync_scan, record, svc)
        record.status = "done"
        _persist_scan(record, security_store)
        # Keep findings in memory (scans are smaller than doc sets)
    except Exception as exc:
        logger.exception("Security job %s failed", job_id)
        record.status = "failed"
        record.error = str(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _findings_to_summaries(findings: list[dict[str, Any]]) -> list[FindingSummary]:
    result: list[FindingSummary] = []
    for f in findings:
        with contextlib.suppress(Exception):
            result.append(FindingSummary(**f))
    return result


def _load_from_store(job_id: str, repo_id: str, request: Request) -> dict[str, Any] | None:
    security_store = getattr(request.app.state, "security_store", None)
    if security_store is None:
        return None
    from aquila_atlas.api.store import SecurityStore  # noqa: PLC0415

    if not isinstance(security_store, SecurityStore):
        return None
    row = security_store.load_scan(job_id)
    if row is not None and row["repo_id"] == repo_id:
        return row
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/security/scan",
    response_model=SecurityScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit security scan job",
)
async def submit_security_scan(
    repo_id: str,
    body: SecurityScanRequest,
    request: Request,
    svc: Svc,
    _auth: Auth,
) -> SecurityScanResponse:
    job_id = str(uuid.uuid4())
    record = SecurityJobRecord(
        job_id=job_id,
        repo_id=repo_id,
        source=body.source,
        token=body.token,
        branch=body.branch,
        semgrep_config=body.semgrep_config,
        run_llm_triage=body.run_llm_triage,
    )
    _security_jobs[job_id] = record
    security_store = getattr(request.app.state, "security_store", None)
    asyncio.create_task(_run_security_job(job_id, svc, security_store))
    return SecurityScanResponse(job_id=job_id, repo_id=repo_id, status="queued")


@router.get(
    "/security/jobs/{job_id}",
    response_model=SecurityScanJob,
    summary="Poll security scan job status",
)
async def get_security_job(
    repo_id: str,
    job_id: str,
    _auth: Auth,
) -> SecurityScanJob:
    record = _security_jobs.get(job_id)
    if record is None or record.repo_id != repo_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return SecurityScanJob(
        job_id=record.job_id,
        repo_id=record.repo_id,
        source=record.source,
        status=record.status,
        completed=record.completed,
        total=record.total,
        current_phase=record.current_phase,
        error=record.error,
        severity_counts=record.severity_counts,
    )


@router.get(
    "/security/scans",
    response_model=SecurityScanListResponse,
    summary="List saved security scans for a repo",
)
async def list_security_scans(
    repo_id: str,
    request: Request,
    _auth: Auth,
) -> SecurityScanListResponse:
    security_store = getattr(request.app.state, "security_store", None)
    if security_store is None:
        return SecurityScanListResponse(repo_id=repo_id, scans=[], total=0)
    from aquila_atlas.api.store import SecurityStore  # noqa: PLC0415

    if not isinstance(security_store, SecurityStore):
        return SecurityScanListResponse(repo_id=repo_id, scans=[], total=0)
    rows = security_store.list_repo_scans(repo_id)
    scans = [SecurityScanMeta(**row) for row in rows]
    return SecurityScanListResponse(repo_id=repo_id, scans=scans, total=len(scans))


@router.get(
    "/security/scans/{job_id}",
    response_model=SecurityReport,
    summary="Get security scan report and findings",
)
async def get_security_scan(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> SecurityReport:
    # Check in-memory first
    record = _security_jobs.get(job_id)
    if record is not None and record.repo_id == repo_id:
        if record.status != "done":
            raise HTTPException(
                status_code=status.HTTP_425_TOO_EARLY,
                detail=f"Job status is '{record.status}', not done yet",
            )
        return SecurityReport(
            job_id=record.job_id,
            repo_id=record.repo_id,
            source=record.source,
            findings=_findings_to_summaries(record.findings),
            report=record.report,
            severity_counts=record.severity_counts,
            tools_used=record.tools_used,
        )

    # Fallback to DB
    row = _load_from_store(job_id, repo_id, request)
    if row is not None:
        return SecurityReport(
            job_id=row["job_id"],
            repo_id=row["repo_id"],
            source=row["source"],
            findings=_findings_to_summaries(row["findings"]),
            report=row["report"],
            severity_counts=row["severity_counts"],
            tools_used=row.get("tools_used") or [],
            created_at=row.get("created_at"),
        )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security scan not found")


@router.delete(
    "/security/scans/{job_id}",
    response_model=SecurityDeleteResponse,
    summary="Delete a security scan record",
)
async def delete_security_scan(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> SecurityDeleteResponse:
    if job_id in _security_jobs and _security_jobs[job_id].repo_id == repo_id:
        del _security_jobs[job_id]

    security_store = getattr(request.app.state, "security_store", None)
    deleted_from_db = False
    if security_store is not None:
        from aquila_atlas.api.store import SecurityStore  # noqa: PLC0415

        if isinstance(security_store, SecurityStore):
            deleted_from_db = security_store.delete_scan(repo_id, job_id)

    return SecurityDeleteResponse(
        success=True,
        job_id=job_id,
        message="Deleted from database" if deleted_from_db else "Removed from memory",
    )
