"""Repository management endpoints."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    DeleteRepoResponse,
    ErrorResponse,
    IngestRequest,
    IngestResponse,
    RepoListResponse,
    RepoStatsResponse,
)
from aquila_atlas.api.tasks import create_job, run_ingestion

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger ingestion",
    description=(
        "Submit a local path for ingestion. The job runs asynchronously in the background. "
        "Poll `GET /repos/{repo_id}/status` or `GET /jobs/{job_id}` for progress."
    ),
    responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}},
)
async def trigger_ingestion(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    _auth: Auth,
) -> IngestResponse:
    record = create_job(
        repo_id=req.repo_id,
        path=req.path,
        source_type=req.source_type,
        github_token=req.github_token,
    )
    background_tasks.add_task(run_ingestion, record.job_id)
    return IngestResponse(job_id=record.job_id, repo_id=record.repo_id, status=record.status)


_FILE_FIELD = File(...)
_FORM_REPO_ID = Form(...)


@router.post(
    "/upload",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a zip for ingestion",
    description=(
        "Upload a `.zip` archive containing source code. "
        "The archive is extracted and ingested asynchronously."
    ),
    responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}},
)
async def upload_zip(
    background_tasks: BackgroundTasks,
    _auth: Auth,
    repo_id: str = _FORM_REPO_ID,
    file: UploadFile = _FILE_FIELD,
) -> IngestResponse:
    zip_data = await file.read()
    record = create_job(
        repo_id=repo_id, path=file.filename or "<upload>", source_type="zip", zip_data=zip_data
    )
    background_tasks.add_task(run_ingestion, record.job_id)
    return IngestResponse(job_id=record.job_id, repo_id=record.repo_id, status=record.status)


@router.get(
    "",
    response_model=RepoListResponse,
    summary="List all ingested repos",
    description="Returns every repository ID that has at least one chunk in the vector store.",
    responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}},
)
def list_repos(svc: Svc, _auth: Auth) -> RepoListResponse:
    repo_ids = svc.list_repo_ids()
    return RepoListResponse(repos=repo_ids, total=len(repo_ids))


@router.get(
    "/{repo_id}/stats",
    response_model=RepoStatsResponse,
    summary="Repo statistics",
    description=(
        "Returns node-type counts from Neo4j and chunk/file counts from Qdrant for the "
        "given repository. Useful for a dashboard overview card."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def repo_stats(repo_id: str, svc: Svc, _auth: Auth) -> RepoStatsResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    raw = svc.get_repo_stats(repo_id)
    return RepoStatsResponse(
        repo_id=repo_id,
        Repository=raw.get("Repository", 0),
        File=raw.get("File", 0),
        Class=raw.get("Class", 0),
        Function=raw.get("Function", 0),
        Method=raw.get("Method", 0),
        relationships=raw.get("relationships", 0),
        chunks=raw.get("chunks", 0),
        files=raw.get("files", 0),
    )


@router.delete(
    "/{repo_id}",
    response_model=DeleteRepoResponse,
    summary="Delete a repo",
    description=(
        "Permanently removes all graph nodes and vector chunks associated with *repo_id*. "
        "Optionally also purges stored chat sessions and/or documentation via query params. "
        "This operation is **irreversible** — re-ingest to restore the data."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def delete_repo(
    repo_id: str,
    request: Request,
    svc: Svc,
    _auth: Auth,
    delete_sessions: bool = Query(False, description="Also delete all chat sessions for this repo"),
    delete_docs: bool = Query(False, description="Also delete all saved documentation for this repo"),
) -> DeleteRepoResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    result = svc.delete_repo(repo_id)

    sessions_deleted = 0
    docs_deleted = 0

    if delete_sessions:
        from aquila_atlas.api.store import SessionStore  # noqa: PLC0415

        store = getattr(request.app.state, "store", None)
        if isinstance(store, SessionStore):
            sessions_deleted = store.delete_all_repo_sessions(repo_id)

    if delete_docs:
        from aquila_atlas.api.routers.docs import _doc_jobs  # noqa: PLC0415
        from aquila_atlas.api.store import DocStore  # noqa: PLC0415

        # Purge in-memory doc jobs for this repo
        to_remove = [jid for jid, rec in _doc_jobs.items() if rec.repo_id == repo_id]
        for jid in to_remove:
            del _doc_jobs[jid]

        doc_store = getattr(request.app.state, "doc_store", None)
        if isinstance(doc_store, DocStore):
            docs_deleted = doc_store.delete_all_repo_docs(repo_id)

    return DeleteRepoResponse(
        repo_id=repo_id,
        graph_nodes_deleted=result["graph_nodes_deleted"],
        vector_chunks_deleted=result["vector_chunks_deleted"],
        sessions_deleted=sessions_deleted,
        docs_deleted=docs_deleted,
    )
