"""Test generation router.

Endpoints
---------
POST   /repos/{repo_id}/tests/generate          — submit async test-gen job
GET    /repos/{repo_id}/tests/jobs/{job_id}      — poll job status + progress
POST   /repos/{repo_id}/tests/jobs/{job_id}/cancel — cancel a running job
GET    /repos/{repo_id}/tests                    — list saved test sets (metadata)
GET    /repos/{repo_id}/tests/{job_id}           — get generated test content
GET    /repos/{repo_id}/tests/{job_id}/download-zip — stream ZIP of all test files
DELETE /repos/{repo_id}/tests/{job_id}           — delete from DB
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from aquila_atlas.api.deps import Auth, CurrentUser, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    TestContentResponse,
    TestDeleteResponse,
    TestGenRequest,
    TestGenResponse,
    TestJobStatus,
    TestListResponse,
    TestMetadata,
)

logger = logging.getLogger("aquila.api.testing")

router = APIRouter(prefix="/repos/{repo_id}", tags=["Test Generation"])

_valid_scopes = {"per_file", "per_module", "entry_points"}

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

TestJobStatusLiteral = Literal["queued", "running", "done", "failed"]


def _uid(user: dict | None) -> str:  # type: ignore[type-arg]
    return user["id"] if user is not None else ""


@dataclass
class TestJobRecord:
    job_id: str
    repo_id: str
    scope: str
    language_filter: list[str] | None
    status: TestJobStatusLiteral = "queued"
    files: dict[str, str] = field(default_factory=dict)
    file_statuses: dict[str, str] = field(default_factory=dict)
    completed: int = 0
    total: int = 0
    current_target: str | None = None
    error: str | None = None
    cancelled: bool = False
    exclude_extensions: list[str] | None = None
    user_id: str = ""


_test_jobs: dict[str, TestJobRecord] = {}

# ---------------------------------------------------------------------------
# TestStore dependency
# ---------------------------------------------------------------------------


def _get_test_store(request: Request) -> Any:
    return getattr(request.app.state, "test_store", None)


TestStoreOrNone = Annotated[object, Depends(_get_test_store)]

# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------


def _sync_generate(record: TestJobRecord, svc: object) -> tuple[dict[str, str], dict[str, str]]:
    from aquila_atlas.testing import GenerationCancelled, generate_tests  # noqa: PLC0415

    def progress(completed: int, total: int, current_target: str | None) -> None:
        if record.cancelled:
            raise GenerationCancelled
        record.completed = completed
        record.total = total
        record.current_target = current_target

    try:
        return generate_tests(
            svc=svc,  # type: ignore[arg-type]
            repo_id=record.repo_id,
            scope=record.scope,  # type: ignore[arg-type]
            language_filter=record.language_filter,
            exclude_extensions=record.exclude_extensions,
            progress_callback=progress,
        )
    except GenerationCancelled as exc:
        return exc.partial, exc.partial_statuses


def _persist_tests(record: TestJobRecord, test_store: object) -> None:
    if not record.files or test_store is None:
        return
    from aquila_atlas.api.store import TestStore  # noqa: PLC0415

    if isinstance(test_store, TestStore):
        test_store.save_tests(
            job_id=record.job_id,
            repo_id=record.repo_id,
            scope=record.scope,
            language_filter=record.language_filter,
            files=record.files,
            file_statuses=record.file_statuses or None,
            user_id=record.user_id,
        )


async def _run_test_job(job_id: str, svc: object, test_store: object) -> None:
    record = _test_jobs.get(job_id)
    if record is None:
        return
    record.status = "running"
    loop = asyncio.get_running_loop()
    try:
        files, file_statuses = await loop.run_in_executor(None, _sync_generate, record, svc)
        record.files = files
        record.file_statuses = file_statuses
        record.status = "done"
        _persist_tests(record, test_store)
        record.files = {}  # free bulk content; metadata kept for polling
    except Exception as exc:
        logger.exception("Test job %s failed", job_id)
        record.status = "failed"
        record.error = str(exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_test_files(
    job_id: str, repo_id: str, request: Request
) -> tuple[dict[str, str], TestJobRecord | None]:
    record = _test_jobs.get(job_id)
    if (
        record is not None
        and record.repo_id == repo_id
        and record.status == "done"
        and record.files
    ):
        return record.files, record
    test_store = getattr(request.app.state, "test_store", None)
    if test_store is not None:
        from aquila_atlas.api.store import TestStore  # noqa: PLC0415

        if isinstance(test_store, TestStore):
            row = test_store.load_tests(job_id)
            if row is not None and row["repo_id"] == repo_id:
                return row["files"], record
    return {}, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/tests/generate",
    response_model=TestGenResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit test generation job",
)
async def generate_tests_endpoint(
    repo_id: str,
    body: TestGenRequest,
    request: Request,
    svc: Svc,
    _auth: Auth,
    user: CurrentUser,
) -> TestGenResponse:
    if body.scope not in _valid_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid scope '{body.scope}'. Valid: {sorted(_valid_scopes)}",
        )
    job_id = str(uuid.uuid4())
    record = TestJobRecord(
        job_id=job_id,
        repo_id=repo_id,
        scope=body.scope,
        language_filter=body.language_filter,
        exclude_extensions=body.exclude_extensions,
        user_id=_uid(user),
    )
    _test_jobs[job_id] = record
    test_store = getattr(request.app.state, "test_store", None)
    asyncio.create_task(_run_test_job(job_id, svc, test_store))
    return TestGenResponse(job_id=job_id, repo_id=repo_id, status="queued")


@router.get(
    "/tests/jobs/{job_id}",
    response_model=TestJobStatus,
    summary="Poll test generation job status",
)
async def get_test_job_status(
    repo_id: str,
    job_id: str,
    _auth: Auth,
) -> TestJobStatus:
    record = _test_jobs.get(job_id)
    if record is None or record.repo_id != repo_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return TestJobStatus(
        job_id=record.job_id,
        repo_id=record.repo_id,
        scope=record.scope,
        language_filter=record.language_filter,
        status=record.status,
        completed=record.completed,
        total=record.total,
        current_target=record.current_target,
        error=record.error,
        files=sorted(record.files.keys()) if record.status == "done" else [],
    )


@router.post(
    "/tests/jobs/{job_id}/cancel",
    response_model=TestJobStatus,
    summary="Cancel a running test generation job",
)
async def cancel_test_job(
    repo_id: str,
    job_id: str,
    _auth: Auth,
) -> TestJobStatus:
    record = _test_jobs.get(job_id)
    if record is None or record.repo_id != repo_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if record.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is already '{record.status}', cannot cancel",
        )
    record.cancelled = True
    return TestJobStatus(
        job_id=record.job_id,
        repo_id=record.repo_id,
        scope=record.scope,
        language_filter=record.language_filter,
        status=record.status,
        completed=record.completed,
        total=record.total,
        current_target=record.current_target,
        error=record.error,
        files=[],
    )


@router.get(
    "/tests",
    response_model=TestListResponse,
    summary="List saved test sets for a repo",
)
async def list_repo_tests(
    repo_id: str,
    request: Request,
    _auth: Auth,
    user: CurrentUser,
) -> TestListResponse:
    test_store = getattr(request.app.state, "test_store", None)
    if test_store is None:
        return TestListResponse(repo_id=repo_id, tests=[], total=0)
    from aquila_atlas.api.store import TestStore  # noqa: PLC0415

    if not isinstance(test_store, TestStore):
        return TestListResponse(repo_id=repo_id, tests=[], total=0)
    uid = _uid(user)
    rows = test_store.list_repo_tests(repo_id, user_id=uid)
    tests = [TestMetadata(**row) for row in rows]
    return TestListResponse(repo_id=repo_id, tests=tests, total=len(tests))


@router.get(
    "/tests/{job_id}",
    response_model=TestContentResponse,
    summary="Get generated test content (memory or DB)",
)
async def get_test_content(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> TestContentResponse:
    record = _test_jobs.get(job_id)
    if record is not None and record.repo_id == repo_id:
        if record.status != "done":
            raise HTTPException(
                status_code=status.HTTP_425_TOO_EARLY,
                detail=f"Job status is '{record.status}', not done yet",
            )
        if record.files:
            return TestContentResponse(
                job_id=record.job_id,
                repo_id=record.repo_id,
                scope=record.scope,
                language_filter=record.language_filter,
                files=record.files,
                file_statuses=record.file_statuses or None,
            )

    test_store = getattr(request.app.state, "test_store", None)
    if test_store is not None:
        from aquila_atlas.api.store import TestStore  # noqa: PLC0415

        if isinstance(test_store, TestStore):
            row = test_store.load_tests(job_id)
            if row is not None and row["repo_id"] == repo_id:
                return TestContentResponse(
                    job_id=row["job_id"],
                    repo_id=row["repo_id"],
                    scope=row["scope"],
                    language_filter=row["language_filter"],
                    files=row["files"],
                    file_statuses=row.get("file_statuses") or None,
                )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test content not found")


@router.get(
    "/tests/{job_id}/download-zip",
    summary="Download all generated test files as a ZIP archive",
)
async def download_tests_zip(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> StreamingResponse:
    files, record = _resolve_test_files(job_id, repo_id, request)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test content not found or not ready",
        )

    scope = record.scope if record else "tests"

    # Gather file_statuses: prefer in-memory record, fallback to DB
    file_statuses: dict[str, str] | None = None
    if record is not None and record.file_statuses:
        file_statuses = record.file_statuses
    else:
        test_store_obj = getattr(request.app.state, "test_store", None)
        if test_store_obj is not None:
            from aquila_atlas.api.store import TestStore as _TS  # noqa: PLC0415, N814

            if isinstance(test_store_obj, _TS):
                row = test_store_obj.load_tests(job_id)
                if row is not None:
                    file_statuses = row.get("file_statuses") or None

    from aquila_atlas.testing._zip import build_test_zip  # noqa: PLC0415

    loop = asyncio.get_running_loop()
    buf = await loop.run_in_executor(None, build_test_zip, files, scope, repo_id, file_statuses)

    filename = f"{repo_id}-tests-{scope}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/tests/{job_id}",
    response_model=TestDeleteResponse,
    summary="Delete saved test set",
)
async def delete_tests(
    repo_id: str,
    job_id: str,
    request: Request,
    _auth: Auth,
) -> TestDeleteResponse:
    if job_id in _test_jobs and _test_jobs[job_id].repo_id == repo_id:
        del _test_jobs[job_id]

    test_store = getattr(request.app.state, "test_store", None)
    deleted_from_db = False
    if test_store is not None:
        from aquila_atlas.api.store import TestStore  # noqa: PLC0415

        if isinstance(test_store, TestStore):
            deleted_from_db = test_store.delete_tests(repo_id, job_id)

    return TestDeleteResponse(
        success=True,
        job_id=job_id,
        message="Deleted from database" if deleted_from_db else "Removed from memory",
    )
