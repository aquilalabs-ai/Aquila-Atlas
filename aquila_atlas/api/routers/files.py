"""File browsing endpoints — list files and inspect chunks for a repo."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    ChunkItem,
    ErrorResponse,
    FileChunksResponse,
    FileListResponse,
)

router = APIRouter(prefix="/repos", tags=["Files"])


@router.get(
    "/{repo_id}/files",
    response_model=FileListResponse,
    summary="List files in a repo",
    description=(
        "Returns every unique file path that has been ingested into the vector store "
        "for *repo_id*, sorted alphabetically."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def list_files(repo_id: str, svc: Svc, _auth: Auth) -> FileListResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    files = svc.list_files(repo_id)
    return FileListResponse(repo_id=repo_id, files=files, total=len(files))


@router.get(
    "/{repo_id}/files/{file_path:path}",
    response_model=FileChunksResponse,
    summary="Get all chunks for a file",
    description=(
        "Returns every stored chunk for a specific file within *repo_id*, "
        "ordered by `start_line`. The `file_path` is URL-encoded, e.g. "
        "`src%2Fauth%2Fservice.py`."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo or file not found"},
    },
)
def get_file_chunks(repo_id: str, file_path: str, svc: Svc, _auth: Auth) -> FileChunksResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    raw_chunks = svc.get_file_chunks(repo_id, file_path)
    if not raw_chunks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{file_path}' not found in repo '{repo_id}'",
        )
    chunks = [
        ChunkItem(
            file_path=str(c.get("file_path", "")),
            chunk_type=str(c.get("chunk_type", "")),
            start_line=int(c.get("start_line", 0)),
            end_line=int(c.get("end_line", 0)),
            qualified_name=str(c.get("qualified_name", "")),
            language=str(c.get("language", "")),
            chunk_index=int(c.get("chunk_index", 0)),
            chunk_total=int(c.get("chunk_total", 1)),
            content=str(c.get("content", "")),
        )
        for c in raw_chunks
    ]
    return FileChunksResponse(
        repo_id=repo_id,
        file_path=file_path,
        chunks=chunks,
        total=len(chunks),
    )
