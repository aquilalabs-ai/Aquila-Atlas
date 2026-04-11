"""Ingestion job status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from aquila_atlas.api.deps import Auth  # noqa: TC001
from aquila_atlas.api.models import ErrorResponse, JobStatus
from aquila_atlas.api.tasks import get_job, latest_job_for_repo

router = APIRouter(tags=["Ingestion"])


def _record_to_status(record: object) -> JobStatus:
    from aquila_atlas.api.tasks import JobRecord  # noqa: PLC0415

    assert isinstance(record, JobRecord)
    return JobStatus(
        job_id=record.job_id,
        repo_id=record.repo_id,
        status=record.status,
        files=record.files,
        chunks=record.chunks,
        error=record.error,
        ingest_type=record.ingest_type,
        changed_files=record.changed_files,
        old_commit_sha=record.old_commit_sha,
        new_commit_sha=record.new_commit_sha,
    )


@router.get(
    "/repos/{repo_id}/status",
    response_model=JobStatus,
    summary="Latest ingestion status for a repo",
    description=(
        "Returns the status of the most recently submitted ingestion job for *repo_id*. "
        "Possible values: `queued`, `running`, `done`, `failed`."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "No job found for this repo"},
    },
)
def repo_ingestion_status(repo_id: str, _auth: Auth) -> JobStatus:
    record = latest_job_for_repo(repo_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No ingestion job found for repo '{repo_id}'",
        )
    return _record_to_status(record)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatus,
    summary="Job status by ID",
    description=(
        "Fetch the status of any ingestion job by its UUID. "
        "The `job_id` is returned in the `POST /repos` response."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
def job_status_by_id(job_id: str, _auth: Auth) -> JobStatus:
    record = get_job(job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return _record_to_status(record)
