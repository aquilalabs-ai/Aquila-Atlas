"""KnowledgeService — unified interface over the graph and vector stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aquila_atlas.config import Settings
    from aquila_atlas.ingestion.metadata import CodeChunk
    from aquila_atlas.knowledge.graph import GraphStore
    from aquila_atlas.knowledge.vector import SearchResult, VectorStore


@dataclass(frozen=True)
class KnowledgeService:
    """Facade that combines Neo4j graph traversal with Qdrant vector search."""

    graph: GraphStore
    vector: VectorStore

    def search(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        file_path: str | None = None,
        chunk_type: str | None = None,
        language: str | None = None,
    ) -> list[SearchResult]:
        """Semantic + keyword hybrid search over ingested code chunks."""
        return self.vector.search(
            query=query,
            repo_id=repo_id,
            top_k=top_k,
            file_path=file_path,
            chunk_type=chunk_type,
            language=language,
        )

    def get_context(self, function_id: str) -> dict[str, object]:
        """Return callers, callees, file, and parent_class from Neo4j."""
        return self.graph.get_context(function_id)

    def list_repo_ids(self) -> list[str]:
        """Return all repository IDs from Neo4j (fast) with Qdrant as fallback."""
        try:
            ids = self.graph.list_repo_ids()
            if ids:
                return ids
        except Exception:  # noqa: BLE001
            pass
        return self.vector.list_repo_ids()

    def get_graph(self, repo_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return all graph nodes and edges for a repository (for visualisation)."""
        return self.graph.get_graph(repo_id)

    def get_repo_stats(self, repo_id: str) -> dict[str, int]:
        """Merge graph + vector stats for *repo_id*."""
        graph_stats = self.graph.get_repo_stats(repo_id)
        vector_stats = self.vector.get_repo_stats(repo_id)
        return {**graph_stats, **vector_stats}

    def list_files(self, repo_id: str) -> list[str]:
        """Return all unique file paths for *repo_id* from Neo4j (fast) with Qdrant fallback."""
        try:
            return self.graph.list_files(repo_id)
        except Exception:  # noqa: BLE001
            pass
        return self.vector.list_files(repo_id)

    def get_file_chunks(self, repo_id: str, file_path: str) -> list[dict[str, Any]]:
        """Return all chunk payloads for a specific file in *repo_id*."""
        return self.vector.get_file_chunks(repo_id, file_path)

    def get_repo_commit_sha(self, repo_id: str) -> str | None:
        """Return the commit SHA last stored for *repo_id*, or None."""
        return self.graph.get_repo_commit_sha(repo_id)

    def delete_files(self, repo_id: str, file_paths: list[str]) -> dict[str, int]:
        """Delete specific files from both graph and vector stores."""
        graph_deleted = self.graph.delete_files(repo_id, file_paths)
        vector_deleted = self.vector.delete_files(repo_id, file_paths)
        return {"graph_nodes_deleted": graph_deleted, "vector_chunks_deleted": vector_deleted}

    def delete_repo(self, repo_id: str) -> dict[str, int]:
        """Delete all data for *repo_id* from both stores."""
        graph_deleted = self.graph.delete_repo(repo_id)
        vector_deleted = self.vector.delete_repo(repo_id)
        return {"graph_nodes_deleted": graph_deleted, "vector_chunks_deleted": vector_deleted}

    def _cypher_read_via_mcp(
        self, cypher: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        """Execute a Cypher query via the configured Neo4j MCP server."""
        import asyncio
        import json

        from aquila_atlas.config import get_settings  # noqa: PLC0415
        from aquila_atlas.reasoning.tools import get_mcp_tools  # noqa: PLC0415

        settings = get_settings()
        if not settings.mcp_url:
            raise RuntimeError("MCP URL is not configured; cannot execute Cypher queries via MCP")

        tools = asyncio.run(get_mcp_tools(settings))
        read_tool = next((t for t in tools if t.name == "read-cypher"), None)
        if read_tool is None:
            raise RuntimeError("MCP tool 'read-cypher' not available")

        result = asyncio.run(read_tool.arun({"query": cypher, "params": params or {}}))

        if isinstance(result, list):
            text = "".join(str(item.get("text", "")) for item in result if isinstance(item, dict))
            if not text:
                return []
            try:
                return json.loads(text)  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Unexpected MCP read-cypher output format; expected JSON"
                ) from exc
        if isinstance(result, str):
            try:
                return json.loads(result)  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Unexpected MCP read-cypher output format; expected JSON"
                ) from exc

        raise RuntimeError("Unexpected MCP read-cypher response type")

    def cypher_read(
        self, cypher: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        """Execute a read-only Cypher query against the graph.

        Uses Neo4j MCP server on the configured mcp_url, as required by policy.
        """
        return self._cypher_read_via_mcp(cypher, params)

    def ingest_chunks(self, chunks: list[CodeChunk], repo_id: str) -> None:
        """Upsert code chunks into the vector store."""
        self.vector.upsert(chunks, repo_id)

    # ------------------------------------------------------------------
    # Graph-aware documentation helpers (pass-throughs to GraphStore)
    # ------------------------------------------------------------------

    def get_import_graph(self, repo_id: str) -> list[tuple[str, str]]:
        """Return ``(importer_file_path, imported_file_path)`` for all intra-repo imports."""
        return self.graph.get_import_graph(repo_id)

    def get_file_graph_context(self, repo_id: str, file_path: str) -> dict[str, Any]:
        """Return graph neighbourhood for a file: imports, importers, in_degree, symbols."""
        return self.graph.get_file_graph_context(repo_id, file_path)

    def get_entry_points(self, repo_id: str) -> list[dict[str, Any]]:
        """Return public entry-point functions with no incoming CALLS edges."""
        return self.graph.get_entry_points(repo_id)

    def get_call_chain(
        self, repo_id: str, start_id: str, max_depth: int = 6
    ) -> list[dict[str, Any]]:
        """BFS via CALLS edges up to *max_depth* hops from *start_id*."""
        return self.graph.get_call_chain(repo_id, start_id, max_depth)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_knowledge_service(settings: Settings | None = None) -> KnowledgeService:
    """Create a :class:`KnowledgeService` from application settings."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.knowledge.graph import get_graph_store  # noqa: PLC0415
    from aquila_atlas.knowledge.vector import get_vector_store  # noqa: PLC0415

    s = settings or get_settings()
    return KnowledgeService(graph=get_graph_store(s), vector=get_vector_store(s))
