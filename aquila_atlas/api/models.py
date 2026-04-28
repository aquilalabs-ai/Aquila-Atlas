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
    license_valid: bool | None = None
    seats_used: int | None = None
    seats_total: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ready",
                    "neo4j": True,
                    "qdrant": True,
                    "license_valid": True,
                    "seats_used": 3,
                    "seats_total": 25,
                }
            ]
        }
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


class RepoSourceResponse(BaseModel):
    path: str
    source_type: str
    has_token: bool = Field(False, description="True if a token was used during ingestion")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "path": "https://github.com/owner/repo",
                    "source_type": "github",
                    "has_token": True,
                }
            ]
        }
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
    commit_sha: str | None = Field(
        None, description="Last ingested commit SHA (null for non-git sources)"
    )

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
        description=(
            "Source type: "
            "'local' (filesystem path), "
            "'github' (GitHub URL), "
            "'gitlab' (GitLab URL — self-hosted or gitlab.com), "
            "'gitea' (Gitea / Forgejo URL), "
            "'git' (any git-cloneable URL: HTTPS, SSH, file://), "
            "'zip' (uploaded zip archive)"
        ),
    )
    path: str = Field(
        "",
        description=(
            "Repository URL or local filesystem path, depending on source_type. "
            "For 'local': absolute path. "
            "For 'github'/'gitlab'/'gitea'/'git': full URL."
        ),
    )
    github_token: str = Field(
        "",
        description=(
            "Access token for the remote source. "
            "GitHub PAT, GitLab PAT, Gitea access token, or bearer token for 'git' HTTPS URLs. "
            "Leave empty for public repos or SSH-authenticated clones."
        ),
    )

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
                    "github_token": "ghp_...",
                },
                {
                    "repo_id": "my-service",
                    "source_type": "gitlab",
                    "path": "https://gitlab.example.com/group/repo",
                    "github_token": "glpat-...",
                },
                {
                    "repo_id": "my-service",
                    "source_type": "gitea",
                    "path": "https://gitea.example.com/owner/repo",
                    "github_token": "your-token",
                },
                {
                    "repo_id": "my-service",
                    "source_type": "git",
                    "path": "git@git.corp.com:team/repo.git",
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
    ingest_type: str = Field("full", description='"full" | "resync"')
    changed_files: int | None = Field(None, description="Files re-indexed (resync only)")
    old_commit_sha: str | None = Field(None, description="Commit SHA before resync")
    new_commit_sha: str | None = Field(None, description="Commit SHA after resync")

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
                    "ingest_type": "full",
                    "changed_files": None,
                    "old_commit_sha": None,
                    "new_commit_sha": None,
                }
            ]
        }
    }


class ResyncResponse(BaseModel):
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
            '"architecture" | "per_module" | "per_file" | "subsystem" | "flows" | "user_guide" | "developer_guide"'
        ),
    )
    style: str = Field("technical", description='"technical" (developer) or "functional" (PM/QA)')
    language: str = Field(
        "en", description="ISO-639-1 language code (en, fr, es, de, zh, ja, pt, ar)"
    )
    targets: list[str] | None = Field(
        None, description="Optional list of specific files/modules to document"
    )
    exclude_extensions: list[str] | None = Field(
        None,
        description=(
            'File extensions to skip (e.g. [".md", ".png"]). '
            "Pass null to use the built-in defaults (images, markup, binaries, lock files). "
            "Pass [] to disable extension filtering entirely."
        ),
    )

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
    files: list[str] = Field(
        default_factory=list, description="Generated filenames (populated on done)"
    )

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
        "json_schema_extra": {"examples": [{"repo_id": "my-service", "docs": [], "total": 0}]}
    }


class DocDeleteResponse(BaseModel):
    success: bool
    job_id: str
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "message": "Deleted",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Test generation
# ---------------------------------------------------------------------------


class TestGenRequest(BaseModel):
    scope: str = Field(
        "per_file",
        description='Test scope: "per_file" | "per_module" | "entry_points"',
    )
    language_filter: list[str] | None = Field(
        None,
        description=(
            "Restrict generation to specific languages "
            '(e.g. ["python", "typescript"]). Null = all supported languages.'
        ),
    )
    exclude_extensions: list[str] | None = Field(
        None,
        description=(
            'File extensions to skip (e.g. [".md", ".png"]). '
            "Null = built-in defaults. [] = no extension filtering."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"scope": "per_file", "language_filter": ["python"], "exclude_extensions": None},
                {"scope": "per_module", "language_filter": None, "exclude_extensions": None},
                {
                    "scope": "entry_points",
                    "language_filter": ["typescript"],
                    "exclude_extensions": None,
                },
            ]
        }
    }


class TestGenResponse(BaseModel):
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


class TestJobStatus(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    language_filter: list[str] | None
    status: str = Field(..., description='"queued" | "running" | "done" | "failed"')
    completed: int = Field(0)
    total: int = Field(0)
    current_target: str | None = Field(None)
    error: str | None = Field(None)
    files: list[str] = Field(
        default_factory=list, description="Generated file paths (populated on done)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "per_file",
                    "language_filter": ["python"],
                    "status": "running",
                    "completed": 3,
                    "total": 12,
                    "current_target": "aquila_atlas/config.py",
                    "error": None,
                    "files": [],
                }
            ]
        }
    }


class TestContentResponse(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    language_filter: list[str] | None
    files: dict[str, str] = Field(..., description="output_path → test code content")
    file_statuses: dict[str, str] | None = Field(
        None,
        description=(
            'output_path → validation status: "validated" | "syntax-only" | "unvalidated"'
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "per_file",
                    "language_filter": None,
                    "files": {"tests/aquila_atlas/test_config.py": "import pytest\n..."},
                    "file_statuses": {"tests/aquila_atlas/test_config.py": "validated"},
                }
            ]
        }
    }


class TestMetadata(BaseModel):
    job_id: str
    repo_id: str
    scope: str
    language_filter: list[str] | None
    created_at: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "scope": "per_file",
                    "language_filter": None,
                    "created_at": "2026-04-25T10:00:00+00:00",
                }
            ]
        }
    }


class TestListResponse(BaseModel):
    repo_id: str
    tests: list[TestMetadata]
    total: int

    model_config = {
        "json_schema_extra": {"examples": [{"repo_id": "my-service", "tests": [], "total": 0}]}
    }


class TestDeleteResponse(BaseModel):
    success: bool
    job_id: str
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "message": "Deleted",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Security scanning
# ---------------------------------------------------------------------------


class SecurityScanRequest(BaseModel):
    source: str = Field(
        ...,
        description=(
            "Local directory path or remote git URL to scan. "
            "Example: '/home/user/myproject' or 'https://github.com/owner/repo'"
        ),
    )
    token: str = Field(
        "",
        description="OAuth/PAT token for private remote repos (ignored for local paths).",
    )
    branch: str = Field("", description="Branch or tag to check out (remote clones only).")
    semgrep_config: str = Field(
        "auto",
        description=(
            "Semgrep rule config (default 'auto' = Semgrep registry auto-select). "
            "Example: 'p/owasp-top-ten', 'p/python', or a local rules file path."
        ),
    )
    run_llm_triage: bool = Field(
        True,
        description="Run LLM false-positive filtering and logic-vulnerability detection.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source": "/home/user/myproject",
                    "token": "",
                    "branch": "",
                    "semgrep_config": "auto",
                    "run_llm_triage": True,
                },
                {
                    "source": "https://github.com/owner/repo",
                    "token": "ghp_...",
                    "branch": "main",
                    "semgrep_config": "p/owasp-top-ten",
                    "run_llm_triage": True,
                },
            ]
        }
    }


class SecurityScanResponse(BaseModel):
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


class FindingSummary(BaseModel):
    file: str
    line: int
    rule_id: str
    severity: str = Field(..., description='"minor" | "major" | "critical"')
    message: str
    cwe: str = ""
    owasp_category: str = ""
    fix_suggestion: str = ""
    source: str = Field(..., description='"semgrep" | "gitleaks" | "trivy" | "checkov" | "llm"')
    confirmed_by_llm: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "file": "src/auth/service.py",
                    "line": 42,
                    "rule_id": "python.django.security.injection.tainted-sql-string",
                    "severity": "critical",
                    "message": "Possible SQL injection via untrusted input",
                    "cwe": "CWE-89",
                    "owasp_category": "A03 - Injection",
                    "fix_suggestion": "Use parameterised queries instead of string formatting.",
                    "source": "semgrep",
                    "confirmed_by_llm": True,
                }
            ]
        }
    }


class SecurityScanJob(BaseModel):
    job_id: str
    repo_id: str
    source: str
    status: str = Field(..., description='"queued" | "running" | "done" | "failed"')
    completed: int = Field(0)
    total: int = Field(4, description="Always 4 phases: resolve, scan, triage, report")
    current_phase: str | None = Field(None)
    error: str | None = Field(None)
    severity_counts: dict[str, int] = Field(
        default_factory=dict, description="{critical: N, major: N, minor: N}"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "source": "/home/user/project",
                    "status": "running",
                    "completed": 2,
                    "total": 4,
                    "current_phase": "Running LLM triage…",
                    "error": None,
                    "severity_counts": {},
                }
            ]
        }
    }


class SecurityReport(BaseModel):
    job_id: str
    repo_id: str
    source: str
    findings: list[FindingSummary]
    report: str = Field(..., description="Full Markdown report")
    severity_counts: dict[str, int]
    tools_used: list[str] = Field(
        default_factory=list,
        description='Tools that ran: ["semgrep", "gitleaks", "LLM triage"]',
    )
    created_at: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "source": "/home/user/project",
                    "findings": [],
                    "report": "# Security Scan Report…",
                    "severity_counts": {"critical": 0, "major": 2, "minor": 5},
                    "created_at": "2026-04-25T10:00:00+00:00",
                }
            ]
        }
    }


class SecurityScanMeta(BaseModel):
    job_id: str
    repo_id: str
    source: str
    severity_counts: dict[str, int]
    created_at: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "repo_id": "my-service",
                    "source": "/home/user/project",
                    "severity_counts": {"critical": 1, "major": 3, "minor": 7},
                    "created_at": "2026-04-25T10:00:00+00:00",
                }
            ]
        }
    }


class SecurityScanListResponse(BaseModel):
    repo_id: str
    scans: list[SecurityScanMeta]
    total: int

    model_config = {
        "json_schema_extra": {"examples": [{"repo_id": "my-service", "scans": [], "total": 0}]}
    }


class SecurityDeleteResponse(BaseModel):
    success: bool
    job_id: str
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "message": "Deleted",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Auth / Identity
# ---------------------------------------------------------------------------


class ActivateRequest(BaseModel):
    """Seat-key activation request (``key`` auth mode only)."""

    seat_key: str = Field(..., description="Vendor-issued RS256-signed seat key JWT")
    email: str = Field(
        ..., description="User e-mail address (must match key if key contains email)"
    )
    display_name: str = Field("", description="Optional display name")
    password: str = Field(..., min_length=8, description="Chosen password (min 8 characters)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "seat_key": "<vendor-signed JWT>",
                    "email": "alice@acme.com",
                    "display_name": "Alice Smith",
                    "password": "S3cur3P@ss!",
                }
            ]
        }
    }


class LoginRequest(BaseModel):
    """Login with email + password (key mode) or AD username + password (ldap mode)."""

    username: str = Field(..., description="E-mail for key mode; AD username for ldap mode")
    password: str
    mode: str = Field("key", description='"key" | "ldap"')

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"username": "alice@acme.com", "password": "S3cur3P@ss!", "mode": "key"},
                {"username": "ACME\\alice", "password": "ADpassword", "mode": "ldap"},
            ]
        }
    }


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str = Field(..., description='"admin" | "user"')

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "access_token": "<JWT>",
                    "refresh_token": "<JWT>",
                    "token_type": "bearer",
                    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "email": "alice@acme.com",
                    "role": "user",
                }
            ]
        }
    }


class RefreshRequest(BaseModel):
    refresh_token: str

    model_config = {"json_schema_extra": {"examples": [{"refresh_token": "<refresh JWT>"}]}}


class UserInfo(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    auth_mode: str
    is_active: bool
    created_at: str
    last_seen_at: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "email": "alice@acme.com",
                    "display_name": "Alice Smith",
                    "role": "user",
                    "auth_mode": "key",
                    "is_active": True,
                    "created_at": "2026-04-26T10:00:00+00:00",
                    "last_seen_at": "2026-04-26T12:00:00+00:00",
                }
            ]
        }
    }


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = None
    display_name: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"is_active": False}, {"role": "admin"}, {"display_name": "Bob Jones"}]
        }
    }


class LicenseStatus(BaseModel):
    valid: bool
    customer_id: str = ""
    customer_name: str = ""
    max_seats: int = 0
    seats_used: int = 0
    seats_available: int = 0
    expires_at: str = ""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "valid": True,
                    "customer_id": "acme-corp",
                    "customer_name": "ACME Corporation",
                    "max_seats": 25,
                    "seats_used": 3,
                    "seats_available": 22,
                    "expires_at": "2027-04-26T00:00:00+00:00",
                }
            ]
        }
    }


class RepoMemberInfo(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str = Field(..., description='"owner" | "member" | "viewer"')

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "email": "alice@acme.com",
                    "display_name": "Alice Smith",
                    "role": "owner",
                }
            ]
        }
    }


class AddRepoMemberRequest(BaseModel):
    email: str
    role: str = Field("member", description='"owner" | "member" | "viewer"')

    model_config = {
        "json_schema_extra": {"examples": [{"email": "bob@acme.com", "role": "member"}]}
    }


# ---------------------------------------------------------------------------
# Errors  (used via HTTPException — documented here for Swagger)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"json_schema_extra": {"examples": [{"detail": "Repo 'my-service' not found"}]}}


# ---------------------------------------------------------------------------
# Admin — repo + system stats
# ---------------------------------------------------------------------------


class RepoAdminInfo(BaseModel):
    repo_id: str
    graph_nodes: int
    graph_relationships: int
    vector_chunks: int
    files: int
    commit_sha: str | None = None


class TableStat(BaseModel):
    table_name: str
    row_count: int
    size_bytes: int | None = None


class QdrantStat(BaseModel):
    collection_name: str
    vectors_count: int
    points_count: int
    segments_count: int
    disk_data_size: int | None = None
    ram_data_size: int | None = None
    status: str


class SystemStatsResponse(BaseModel):
    qdrant: list[QdrantStat]
    postgres: list[TableStat]


class PurgeResult(BaseModel):
    sessions_purged: int
    doc_rows_purged: int
    test_rows_purged: int
    security_rows_purged: int
    auth_sessions_purged: int
