"""Aquila-Atlas FastAPI application factory.

Instantiate with ``create_app()`` or import the pre-built ``app`` singleton
that is registered as the ``aquila-serve`` entry-point.

API surface
-----------
Tag              Endpoints
---------------- -----------------------------------------------------------
Health           GET  /health
                 GET  /health/ready
Repositories     POST /repos
                 GET  /repos
                 GET  /repos/{repo_id}/stats
                 DELETE /repos/{repo_id}
Ingestion        GET  /repos/{repo_id}/status
                 GET  /jobs/{job_id}
Files            GET  /repos/{repo_id}/files
                 GET  /repos/{repo_id}/files/{file_path}
Search           GET  /repos/{repo_id}/search
Chat             POST /repos/{repo_id}/chat
                 GET  /repos/{repo_id}/sessions
                 DELETE /repos/{repo_id}/sessions/{session_id}
Graph            GET  /repos/{repo_id}/graph
                 GET  /repos/{repo_id}/graph/stats
                 POST /repos/{repo_id}/graph/query
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from aquila_atlas.api.routers import chat, docs, files, graph, health, ingestion, repos, search

if TYPE_CHECKING:
    from aquila_atlas.reasoning.agent import CodebaseAgent as CodebaseAgent


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    import logging  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415
    from aquila_atlas.reasoning.tools import get_mcp_tools  # noqa: PLC0415

    _log = logging.getLogger("aquila.api")

    from aquila_atlas.api.store import create_store  # noqa: PLC0415

    app.state.svc = get_knowledge_service()
    app.state.sessions = {}
    app.state.session_meta = {}  # session_id → metadata (title, created_at, …)

    # Session store — persists chat history across restarts
    try:
        app.state.store = create_store(get_settings().postgres_url)
        _log.info("Session store connected to PostgreSQL at %s", get_settings().postgres_url)
    except Exception:
        _log.warning(
            "PostgreSQL unavailable — sessions will not persist across restarts", exc_info=True
        )
        app.state.store = None

    # Doc store — persists generated documentation across restarts
    from aquila_atlas.api.store import create_doc_store  # noqa: PLC0415

    try:
        app.state.doc_store = create_doc_store(get_settings().postgres_url)
        _log.info("Doc store connected to PostgreSQL")
    except Exception:
        _log.warning(
            "PostgreSQL unavailable — docs will not persist across restarts", exc_info=True
        )
        app.state.doc_store = None

    # Load MCP tools once at startup so every chat session gets them
    try:
        app.state.mcp_tools = await get_mcp_tools(get_settings())
        _log.info("MCP tools loaded: %s", [t.name for t in app.state.mcp_tools])
    except Exception:
        _log.warning("MCP tools unavailable — continuing without them", exc_info=True)
        app.state.mcp_tools = []

    yield
    app.state.svc.graph.close()


# ---------------------------------------------------------------------------
# Custom OpenAPI schema  (richer metadata, tag ordering, external docs)
# ---------------------------------------------------------------------------

_TAG_METADATA = [
    {
        "name": "Health",
        "description": (
            "Liveness and readiness probes. "
            "Use `GET /health` as a Kubernetes **liveness** probe and "
            "`GET /health/ready` as a **readiness** probe."
        ),
    },
    {
        "name": "Repositories",
        "description": (
            "Manage repository registrations. Trigger ingestion jobs, list "
            "ingested repos, inspect statistics, or permanently delete a repo "
            "from both Neo4j and Qdrant."
        ),
    },
    {
        "name": "Ingestion",
        "description": (
            "Monitor background ingestion jobs. Jobs are submitted via "
            "`POST /repos` and processed asynchronously. Poll these endpoints "
            "for progress."
        ),
    },
    {
        "name": "Files",
        "description": (
            "Browse files that have been ingested for a repository. "
            "List all file paths or drill down to the individual code chunks "
            "stored for a specific file."
        ),
    },
    {
        "name": "Search",
        "description": (
            "Hybrid dense + sparse (BM25) semantic search over ingested code chunks. "
            "Results are merged with Reciprocal Rank Fusion for maximum recall."
        ),
    },
    {
        "name": "Chat",
        "description": (
            "Multi-turn AI-powered codebase Q&A. "
            "Supports **SSE streaming** (default) and plain JSON responses. "
            "Sessions maintain conversation history across requests."
        ),
    },
    {
        "name": "Graph",
        "description": (
            "Access the Neo4j knowledge graph. Retrieve full graph data for "
            "visualisation, fetch aggregated statistics, or execute arbitrary "
            "read-only Cypher queries."
        ),
    },
    {
        "name": "Documentation",
        "description": (
            "AI-powered multi-file documentation generation. Submit async jobs with "
            "scope (architecture, per_module, per_file, subsystem, flows), style, and "
            "language. Poll for progress, download as ZIP, and browse saved docs."
        ),
    },
]


def _custom_openapi(app: FastAPI) -> dict:  # type: ignore[type-arg]
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=_TAG_METADATA,
    )
    # Mark the X-API-Key security scheme
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "API key for authentication. Set `API_KEY` in `.env`. "
            "Leave `API_KEY` empty to run in open / dev mode (no auth required)."
        ),
    }
    schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    application = FastAPI(
        title="Aquila-Atlas API",
        description=(
            "## The Atlas of your codebase\n\n"
            "Aquila-Atlas ingests source code into a **Neo4j knowledge graph** and a "
            "**Qdrant hybrid vector store**, then exposes AI-powered search and "
            "multi-turn Q&A via a clean REST interface.\n\n"
            "### Quick start\n"
            "1. `POST /repos` — submit a local path for ingestion\n"
            "2. `GET /repos/{repo_id}/status` — wait for `status: done`\n"
            "3. `POST /repos/{repo_id}/chat` — ask questions about the code\n\n"
            "### Authentication\n"
            "Set `API_KEY` in `.env` and pass the value in the `X-API-Key` header. "
            "Leave `API_KEY` empty to run without auth (dev / local mode).\n\n"
            "### Streaming\n"
            "Chat responses default to **Server-Sent Events** (`text/event-stream`). "
            "Set `stream: false` in the request body for a plain JSON response."
        ),
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Override OpenAPI schema builder
    application.openapi = lambda: _custom_openapi(application)  # type: ignore[method-assign]

    # CORS — allow the Vite dev server and any configured frontend origin
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    cors_origins = getattr(
        settings, "cors_origins", ["http://localhost:3000", "http://localhost:5173"]
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    application.include_router(health.router)
    application.include_router(repos.router)
    application.include_router(ingestion.router)
    application.include_router(files.router)
    application.include_router(search.router)
    application.include_router(chat.router)
    application.include_router(graph.router)
    application.include_router(docs.router)

    return application


# Pre-built singleton used by uvicorn / CLI
app = create_app()
