"""Pydantic request / response models for the Aquila-Atlas REST API.

Every public model includes ``model_config`` with ``json_schema_extra`` so
FastAPI's auto-generated Swagger UI shows realistic request/response examples.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str

    model_config = {"json_schema_extra": {"examples": [{"status": "ok", "version": "0.1.0"}]}}


class ReadinessResponse(BaseModel):
    status: str  # "ready" | "degraded"
    neo4j: bool
    qdrant: bool

    model_config = {
        "json_schema_extra": {"examples": [{"status": "ready", "neo4j": True, "qdrant": True}]}
    }


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------


class RepoSummary(BaseModel):
    repo_id: str

    model_config = {"json_schema_extra": {"examples": [{"repo_id": "my-service"}]}}


class RepoListResponse(BaseModel):
    repos: list[str]
    total: int

    model_config = {
        "json_schema_extra": {"examples": [{"repos": ["my-service", "frontend-app"], "total": 2}]}
    }


class RepoStatsResponse(BaseModel):
    repo_id: str
    Repository: int = Field(0, description="Repository nodes")
    File: int = Field(0, description="File nodes")
    Class: int = Field(0, description="Class nodes")
    Function: int = Field(0, description="Function nodes")
    Method: int = Field(0, description="Method nodes")
    relationships: int = Field(0, description="Total graph relationships")
    chunks: int = Field(0, description="Vector chunks stored")
    files: int = Field(0, description="Unique files in vector store")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "Repository": 1,
                    "File": 24,
                    "Class": 8,
                    "Function": 63,
                    "Method": 112,
                    "relationships": 340,
                    "chunks": 198,
                    "files": 24,
                }
            ]
        }
    }


class DeleteRepoResponse(BaseModel):
    repo_id: str
    graph_nodes_deleted: int
    vector_chunks_deleted: int
    sessions_deleted: int = 0
    docs_deleted: int = 0

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "graph_nodes_deleted": 208,
                    "vector_chunks_deleted": 198,
                    "sessions_deleted": 5,
                    "docs_deleted": 2,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    repo_id: str = Field(..., description="Unique identifier for this repository")
    source_type: str = Field(
        "local",
        description="Source type: 'local' (filesystem path), 'github' (GitHub URL), or 'zip' (uploaded zip)",
    )
    path: str = Field(
        "",
        description="Local filesystem path (source_type=local) or GitHub URL (source_type=github)",
    )
    github_token: str = Field("", description="Optional GitHub PAT for private repos")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "source_type": "local",
                    "path": "/home/user/projects/my-service",
                },
                {
                    "repo_id": "my-service",
                    "source_type": "github",
                    "path": "https://github.com/owner/repo",
                },
            ]
        }
    }


class IngestResponse(BaseModel):
    job_id: str
    repo_id: str
    status: str = Field(..., description='"queued" immediately after submission')

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "status": "queued",
                }
            ]
        }
    }


class JobStatus(BaseModel):
    job_id: str
    repo_id: str
    status: str = Field(..., description='"queued" | "running" | "done" | "failed"')
    files: int | None = Field(None, description="Files discovered")
    chunks: int | None = Field(None, description="Chunks indexed")
    error: str | None = Field(None, description="Error message if status=failed")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "status": "done",
                    "files": 24,
                    "chunks": 198,
                    "error": None,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class FileListResponse(BaseModel):
    repo_id: str
    files: list[str]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "files": [
                        "src/auth/service.py",
                        "src/auth/models.py",
                        "src/core/config.py",
                    ],
                    "total": 3,
                }
            ]
        }
    }


class ChunkItem(BaseModel):
    file_path: str
    chunk_type: str
    start_line: int
    end_line: int
    qualified_name: str
    language: str
    chunk_index: int
    chunk_total: int
    content: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "file_path": "src/auth/service.py",
                    "chunk_type": "function",
                    "start_line": 42,
                    "end_line": 58,
                    "qualified_name": "authenticate_user",
                    "language": "Python",
                    "chunk_index": 0,
                    "chunk_total": 1,
                    "content": "def authenticate_user(username, password):\n    ...",
                }
            ]
        }
    }


class FileChunksResponse(BaseModel):
    repo_id: str
    file_path: str
    chunks: list[ChunkItem]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "file_path": "src/auth/service.py",
                    "chunks": [],
                    "total": 0,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchResultItem(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str
    qualified_name: str
    language: str
    score: float
    content: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "file_path": "src/auth/service.py",
                    "start_line": 42,
                    "end_line": 58,
                    "chunk_type": "function",
                    "qualified_name": "authenticate_user",
                    "language": "Python",
                    "score": 0.9123,
                    "content": "def authenticate_user(username, password):\n    ...",
                }
            ]
        }
    }


class SearchResponse(BaseModel):
    query: str
    repo_id: str
    results: list[SearchResultItem]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "how does authentication work",
                    "repo_id": "my-service",
                    "results": [],
                    "total": 0,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message / question")
    session_id: str | None = Field(
        None,
        description="Session token from a prior response — omit to start a new conversation",
    )
    stream: bool = Field(True, description="Use SSE streaming (true) or wait for full JSON (false)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "How does the authentication flow work?",
                    "session_id": None,
                    "stream": False,
                }
            ]
        }
    }


class ChatResponse(BaseModel):
    response: str
    session_id: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "response": "Authentication is handled in `src/auth/service.py:42`...",
                    "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                }
            ]
        }
    }


class SessionCreateRequest(BaseModel):
    title: str = Field("New Chat", description="Display name for this conversation")

    model_config = {"json_schema_extra": {"examples": [{"title": "Auth flow investigation"}]}}


class SessionInfo(BaseModel):
    session_id: str
    repo_id: str
    title: str
    created_at: str = Field(..., description="ISO-8601 UTC timestamp")
    message_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                    "repo_id": "my-service",
                    "title": "How does auth work?",
                    "created_at": "2026-04-03T10:00:00+00:00",
                    "message_count": 4,
                }
            ]
        }
    }


class SessionCreateResponse(BaseModel):
    session_id: str
    repo_id: str
    title: str
    created_at: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                    "repo_id": "my-service",
                    "title": "New Chat",
                    "created_at": "2026-04-03T10:00:00+00:00",
                }
            ]
        }
    }


class SessionListResponse(BaseModel):
    repo_id: str
    sessions: list[SessionInfo]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "sessions": [
                        {
                            "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                            "repo_id": "my-service",
                            "title": "How does auth work?",
                            "created_at": "2026-04-03T10:00:00+00:00",
                            "message_count": 4,
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class SessionStoreInfo(BaseModel):
    repo_id: str
    repo_sessions: int = Field(0, description="Persisted sessions for this repo")
    total_sessions: int = Field(0, description="Total persisted sessions across all repos")
    sessions_by_repo: dict[str, int] = Field(
        {}, description="Persisted session counts grouped by repo_id"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "repo_sessions": 5,
                    "total_sessions": 12,
                    "sessions_by_repo": {
                        "my-service": 5,
                        "frontend-app": 7,
                    },
                }
            ]
        }
    }


class SessionDeleteResponse(BaseModel):
    session_id: str
    deleted: bool

    model_config = {
        "json_schema_extra": {
            "examples": [{"session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "deleted": True}]
        }
    }


class SessionResetResponse(BaseModel):
    session_id: str
    cleared: bool

    model_config = {
        "json_schema_extra": {
            "examples": [{"session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "cleared": True}]
        }
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str
    label: str = Field(..., description="Node type: Repository | File | Class | Function | Method")
    properties: dict[str, object]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "my-service:src/auth/service.py:authenticate_user",
                    "label": "Function",
                    "properties": {
                        "name": "authenticate_user",
                        "start_line": 42,
                        "end_line": 58,
                    },
                }
            ]
        }
    }


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = Field(
        ...,
        description="Relationship type: CONTAINS | DEFINES | CALLS | IMPORTS | HAS_METHOD",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source": "my-service:src/auth/service.py",
                    "target": "my-service:src/auth/service.py:authenticate_user",
                    "type": "DEFINES",
                }
            ]
        }
    }


class GraphResponse(BaseModel):
    repo_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    node_count: int
    edge_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "nodes": [],
                    "edges": [],
                    "node_count": 0,
                    "edge_count": 0,
                }
            ]
        }
    }


class GraphStatsResponse(BaseModel):
    repo_id: str
    node_counts: dict[str, int] = Field(
        ..., description="Per-label node counts, e.g. {File: 24, Function: 63}"
    )
    relationship_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo_id": "my-service",
                    "node_counts": {
                        "Repository": 1,
                        "File": 24,
                        "Class": 8,
                        "Function": 63,
                        "Method": 112,
                    },
                    "relationship_count": 340,
                }
            ]
        }
    }


class CypherRequest(BaseModel):
    cypher: str = Field(..., description="Read-only Cypher query to execute against the graph")
    params: dict[str, object] = Field(default_factory=dict, description="Named parameters")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "cypher": (
                        "MATCH (f:Function {repo_id: $repo_id}) "
                        "RETURN f.name AS name, f.file_path AS file ORDER BY name LIMIT 20"
                    ),
                    "params": {"repo_id": "my-service"},
                }
            ]
        }
    }


class CypherResponse(BaseModel):
    rows: list[dict[str, object]]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "rows": [{"name": "authenticate_user", "file": "src/auth/service.py"}],
                    "total": 1,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Documentation generation
# ---------------------------------------------------------------------------


class DocGenRequest(BaseModel):
    scope: str = Field(
        "architecture",
        description=(
            "Documentation scope: "
            '"architecture" | "per_module" | "per_file" | "subsystem" | "flows"'
        ),
    )
    style: str = Field("technical", description='"technical" (developer) or "functional" (PM/QA)')
    language: str = Field("en", description="ISO-639-1 language code (en, fr, es, de, zh, ja, pt, ar)")
    targets: list[str] | None = Field(None, description="Optional list of specific files/modules to document")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"scope": "architecture", "style": "technical", "language": "en"},
                {"scope": "per_module", "style": "functional", "language": "fr"},
                {"scope": "subsystem", "style": "technical", "language": "en"},
                {"scope": "flows", "style": "technical", "language": "en"},
            ]
        }
    }


class DocGenResponse(BaseModel):
    job_id: str
    repo_id: str
    status: str = Field(..., description='"queued" immediately after submission')

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "status": "queued",
                }
            ]
        }
    }


class DocJobStatus(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    style: str
    language: str
    status: str = Field(..., description='"queued" | "running" | "done" | "failed"')
    completed: int = Field(0)
    total: int = Field(0)
    current_target: str | None = Field(None)
    error: str | None = Field(None)
    files: list[str] = Field(default_factory=list, description="Generated filenames (populated on done)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "architecture",
                    "style": "technical",
                    "language": "en",
                    "status": "running",
                    "completed": 2,
                    "total": 5,
                    "current_target": "api",
                    "error": None,
                    "files": [],
                }
            ]
        }
    }


class DocContentResponse(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    style: str
    language: str
    files: dict[str, str] = Field(..., description="filename → markdown content")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "architecture",
                    "style": "technical",
                    "language": "en",
                    "files": {"architecture.md": "# Architecture\n..."},
                }
            ]
        }
    }


class DocMetadata(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    style: str
    language: str
    created_at: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "architecture",
                    "style": "technical",
                    "language": "en",
                    "created_at": "2026-04-03T10:00:00+00:00",
                }
            ]
        }
    }


class DocListResponse(BaseModel):
    repo_id: str
    docs: list[DocMetadata]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [{"repo_id": "my-service", "docs": [], "total": 0}]
        }
    }


class DocDeleteResponse(BaseModel):
    success: bool
    job_id: str
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"success": True, "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "message": "Deleted"}
            ]
        }
    }


# ---------------------------------------------------------------------------
# Errors  (used via HTTPException — documented here for Swagger)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"json_schema_extra": {"examples": [{"detail": "Repo 'my-service' not found"}]}}
