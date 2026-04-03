"""Graph endpoints — visualisation data, stats, and raw Cypher queries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from aquila_atlas.api.deps import Auth, Svc  # noqa: TC001
from aquila_atlas.api.models import (
    CypherRequest,
    CypherResponse,
    ErrorResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    GraphStatsResponse,
)

router = APIRouter(prefix="/repos", tags=["Graph"])


@router.get(
    "/{repo_id}/graph",
    response_model=GraphResponse,
    summary="Full graph data",
    description=(
        "Returns **all nodes and edges** for *repo_id* as a graph suitable for "
        "rendering with D3, Cytoscape, or similar visualisation libraries.\n\n"
        "Node `label` values: `Repository`, `File`, `Class`, `Function`, `Method`.\n\n"
        "Edge `type` values: `CONTAINS`, `DEFINES`, `CALLS`, `IMPORTS`, `HAS_METHOD`."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def get_graph(repo_id: str, svc: Svc, _auth: Auth) -> GraphResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    data = svc.get_graph(repo_id)
    nodes = [
        GraphNode(
            id=str(n["id"]),
            label=str(n["label"]),
            properties={k: v for k, v in n["properties"].items() if k != "source"},
        )
        for n in data["nodes"]
    ]
    edges = [
        GraphEdge(
            source=str(e["source"]),
            target=str(e["target"]),
            type=str(e["type"]),
        )
        for e in data["edges"]
    ]
    return GraphResponse(
        repo_id=repo_id,
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
    )


@router.get(
    "/{repo_id}/graph/stats",
    response_model=GraphStatsResponse,
    summary="Graph statistics",
    description=(
        "Returns per-label node counts and total relationship count from Neo4j. "
        "Faster than fetching the full graph — useful for dashboard overview cards."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def graph_stats(repo_id: str, svc: Svc, _auth: Auth) -> GraphStatsResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    raw = svc.graph.get_repo_stats(repo_id)
    relationships = raw.pop("relationships", 0)
    return GraphStatsResponse(
        repo_id=repo_id,
        node_counts=raw,
        relationship_count=relationships,
    )


@router.post(
    "/{repo_id}/graph/query",
    response_model=CypherResponse,
    summary="Execute a Cypher query",
    description=(
        "Run an **arbitrary read-only Cypher query** against the Neo4j graph for *repo_id*.\n\n"
        "The query executes as-is — use `LIMIT` to avoid large result sets. "
        "Write operations (`CREATE`, `MERGE`, `DELETE`, `SET`) are not prevented at the API "
        "level; use a read-only Neo4j user in production if needed.\n\n"
        "**Example query:**\n"
        "```cypher\n"
        "MATCH (f:Function {repo_id: $repo_id})\n"
        "RETURN f.name AS name, f.file_path AS file\n"
        "ORDER BY name LIMIT 20\n"
        "```"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Cypher syntax or execution error"},
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        404: {"model": ErrorResponse, "description": "Repo not found"},
    },
)
def cypher_query(
    repo_id: str,
    req: CypherRequest,
    svc: Svc,
    _auth: Auth,
) -> CypherResponse:
    if repo_id not in svc.list_repo_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repo '{repo_id}' not found",
        )
    try:
        rows = svc.cypher_read(req.cypher, req.params or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cypher error: {exc}",
        ) from exc
    return CypherResponse(rows=rows, total=len(rows))
