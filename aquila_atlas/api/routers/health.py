"""Health check endpoints."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Request

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
        "Use as a Kubernetes readiness probe. "
        "Also reports license validity and seat counts when auth is enabled."
    ),
    responses={503: {"model": ErrorResponse, "description": "One or more backends unreachable"}},
)
def readiness(request: Request) -> ReadinessResponse:
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

    # License info — only populated when auth is enabled and auth store is available
    license_valid: bool | None = None
    seats_used: int | None = None
    seats_total: int | None = None

    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is not None:
        try:
            lic = auth_store.load_license()
            if lic is not None:
                from datetime import datetime  # noqa: PLC0415

                license_valid = lic["expires_at"] > datetime.now(tz=UTC)
                seats_used = auth_store.count_active_users()
                seats_total = lic["max_seats"]
        except Exception:  # noqa: BLE001
            pass

    overall = "ready" if (neo4j_ok and qdrant_ok) else "degraded"
    return ReadinessResponse(
        status=overall,
        neo4j=neo4j_ok,
        qdrant=qdrant_ok,
        license_valid=license_valid,
        seats_used=seats_used,
        seats_total=seats_total,
    )
