"""Search endpoints — hybrid semantic + keyword code search."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import ErrorResponse, SearchResponse, SearchResultItem

router = APIRouter(prefix="/repos", tags=["Search"])


@router.get(
    "/{repo_id}/search",
    response_model=SearchResponse,
    summary="Hybrid semantic search",
    description=(
        "Runs a **hybrid dense + sparse (BM25) search** over ingested code chunks "
        "and merges results with Reciprocal Rank Fusion. "
        "Optionally narrow results by file path, entity type, or language.\n\n"
        "**Chunk types:** `file`, `class`, `function`, `method`\n\n"
        "**Example:** `?q=how+does+auth+work&chunk_type=function&top_k=5`"
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def search(
    repo_id: str,
    svc: Svc,
    _auth: Auth,
    q: str = Query(..., description="Natural language search query"),
    top_k: int = Query(10, ge=1, le=50, description="Maximum number of results (1-50)"),
    file: str | None = Query(None, description="Filter by exact file path"),
    chunk_type: str | None = Query(
        None, description="Filter by entity type: `file`, `class`, `function`, `method`"
    ),
    language: str | None = Query(None, description="Filter by language, e.g. `Python`"),
) -> SearchResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    results = svc.search(
        query=q,
        repo_id=repo_id,
        top_k=top_k,
        file_path=file,
        chunk_type=chunk_type,
        language=language,
    )
    return SearchResponse(
        query=q,
        repo_id=repo_id,
        results=[
            SearchResultItem(
                file_path=r.file_path,
                start_line=r.start_line,
                end_line=r.end_line,
                chunk_type=r.chunk_type,
                qualified_name=r.qualified_name,
                language=r.language,
                score=r.score,
                content=r.content,
            )
            for r in results
        ],
        total=len(results),
    )
