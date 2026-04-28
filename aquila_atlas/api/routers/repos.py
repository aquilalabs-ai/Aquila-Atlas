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

from aquila_atlas.api.deps import Auth, CurrentUser, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    DeleteRepoResponse,
    ErrorResponse,
    IngestRequest,
    IngestResponse,
    RepoListResponse,
    RepoSourceResponse,
    RepoStatsResponse,
    ResyncResponse,
)
from aquila_atlas.api.tasks import create_job, create_resync_job, run_ingestion, run_resync

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
    user: CurrentUser,
    svc: Svc,
    request: Request,
) -> IngestResponse:
    # If the repo already exists, just grant the requesting user access to it
    # rather than re-ingesting all data.
    if req.repo_id in svc.list_repo_ids():
        if user is not None:
            auth_store = getattr(request.app.state, "auth_store", None)
            if auth_store is not None:
                try:
                    existing = auth_store.get_repo_member(req.repo_id, user["id"])
                    if not existing:
                        auth_store.add_repo_member(req.repo_id, user["id"], "member")
                except Exception:  # noqa: BLE001
                    pass
        return IngestResponse(job_id="", repo_id=req.repo_id, status="already_exists")

    record = create_job(
        repo_id=req.repo_id,
        path=req.path,
        source_type=req.source_type,
        github_token=req.github_token,
    )
    background_tasks.add_task(run_ingestion, record.job_id)

    # Register the submitting user as repo owner when auth is enabled
    if user is not None:
        auth_store = getattr(request.app.state, "auth_store", None)
        if auth_store is not None:
            import contextlib  # noqa: PLC0415

            with contextlib.suppress(Exception):
                auth_store.add_repo_member(req.repo_id, user["id"], "owner")

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


@router.post(
    "/{repo_id}/resync",
    response_model=ResyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resync embeddings from new commits",
    description=(
        "Detect commits made since the last ingest, compute the diff, and re-embed "
        "only the changed files.  Requires the repo to have been ingested at least once "
        "with a git-tracked source (local path or GitHub URL). "
        "Poll `GET /jobs/{job_id}` for progress; the response includes `changed_files`, "
        "`old_commit_sha`, and `new_commit_sha` when done."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
        409: {
            "model": ErrorResponse,
            "description": "Repo already up to date or resync not supported",
        },
    },
)
async def resync_repo(
    repo_id: str,
    background_tasks: BackgroundTasks,
    svc: Svc,
    _auth: Auth,
    path: str = Query(
        "", description="Local path or GitHub URL (required for local/github sources)"
    ),
    source_type: str = Query("local", description='"local" or "github"'),
    github_token: str = Query("", description="Optional GitHub PAT for private repos"),
) -> ResyncResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    if source_type == "zip":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resync is not supported for zip sources — re-ingest instead.",
        )
    record = create_resync_job(
        repo_id=repo_id,
        path=path,
        source_type=source_type,
        github_token=github_token,
    )
    background_tasks.add_task(run_resync, record.job_id)
    return ResyncResponse(job_id=record.job_id, repo_id=record.repo_id, status=record.status)


@router.get(
    "",
    response_model=RepoListResponse,
    summary="List all ingested repos",
    description="Returns every repository ID that has at least one chunk in the vector store.",
    responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}},
)
def list_repos(svc: Svc, _auth: Auth, user: CurrentUser, request: Request) -> RepoListResponse:
    repo_ids = svc.list_repo_ids()

    # When auth is enabled, non-admin users only see repos they are members of.
    if user is not None and user.get("role") != "admin":
        auth_store = getattr(request.app.state, "auth_store", None)
        if auth_store is not None:
            try:
                allowed = set(auth_store.list_user_repos(user["id"]))
                repo_ids = [r for r in repo_ids if r in allowed]
            except Exception:  # noqa: BLE001
                pass  # degrade gracefully — return full list on store error

    return RepoListResponse(repos=repo_ids, total=len(repo_ids))


@router.get(
    "/{repo_id}/source",
    response_model=RepoSourceResponse,
    summary="Repo ingestion source",
    description="Returns the path and source type from the most recent ingestion job for the repo.",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found or no job on record"},
    },
)
def get_repo_source(repo_id: str, svc: Svc, _auth: Auth) -> RepoSourceResponse:
    from aquila_atlas.api.tasks import latest_job_for_repo  # noqa: PLC0415

    # Try the job store first (has token info); fall back to Neo4j (survives restarts).
    # Deliberately avoid svc.list_repo_ids() here — it can trigger expensive Qdrant scroll.
    job = latest_job_for_repo(repo_id)
    if job:
        return RepoSourceResponse(
            path=job.path,
            source_type=job.source_type,
            has_token=bool(job.github_token),
        )

    graph_src = svc.graph.get_repo_source(repo_id)
    if graph_src and graph_src.get("label") and graph_src.get("source_type"):
        return RepoSourceResponse(
            path=str(graph_src["label"]),
            source_type=str(graph_src["source_type"]),
            has_token=bool(graph_src.get("has_token", False)),
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Repo '{repo_id}' not found or no ingestion job on record",
    )


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
        commit_sha=svc.get_repo_commit_sha(repo_id),
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
    delete_docs: bool = Query(
        False, description="Also delete all saved documentation for this repo"
    ),
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
