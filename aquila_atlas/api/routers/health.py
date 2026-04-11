"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from aquila_atlas.api.models import ErrorResponse, HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["Health"])

_VERSION = "0.1.0"


@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns `status: ok` immediately. Use as a Kubernetes liveness probe.",
)
def liveness() -> HealthResponse:
    return HealthResponse(status="ok", version=_VERSION)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Checks connectivity to Neo4j and Qdrant. "
        "Returns `status: ready` only when both backends are reachable. "
        "Use as a Kubernetes readiness probe."
    ),
    responses={503: {"model": ErrorResponse, "description": "One or more backends unreachable"}},
)
def readiness() -> ReadinessResponse:
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.knowledge.graph import get_graph_store  # noqa: PLC0415
    from aquila_atlas.knowledge.vector import get_vector_store  # noqa: PLC0415

    s = get_settings()
    neo4j_ok = False
    qdrant_ok = False

    try:
        gs = get_graph_store(s)
        gs._driver.verify_connectivity()
        neo4j_ok = True
    except Exception:  # noqa: BLE001
        pass

    try:
        vs = get_vector_store(s)
        vs._client.get_collections()
        qdrant_ok = True
    except Exception:  # noqa: BLE001
        pass

    overall = "ready" if (neo4j_ok and qdrant_ok) else "degraded"
    return ReadinessResponse(status=overall, neo4j=neo4j_ok, qdrant=qdrant_ok)
