"""KnowledgeService — unified interface over the graph and vector stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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

    def ingest_chunks(self, chunks: list[CodeChunk], repo_id: str) -> None:
        """Upsert code chunks into the vector store."""
        self.vector.upsert(chunks, repo_id)


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
