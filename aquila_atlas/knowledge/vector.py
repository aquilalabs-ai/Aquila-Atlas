"""Qdrant vector store — hybrid dense + sparse search over code chunks."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import CodeChunk
from aquila_atlas.ingestion.sources import EXT_TO_LANG

if TYPE_CHECKING:
    from openai import OpenAI
    from qdrant_client import QdrantClient
    from aquila_atlas.config import Settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "code_chunks"
_VOCAB_SIZE = 65536

# ---------------------------------------------------------------------------
# Sparse vector helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())


def _sparse_vector(text: str) -> tuple[list[int], list[float]]:
    """Bag-of-words sparse vector with hash-based indices."""
    counts = Counter(_tokenize(text))
    deduped: dict[int, float] = {}
    for token, count in counts.items():
        idx = hash(token) % _VOCAB_SIZE
        deduped[idx] = deduped.get(idx, 0.0) + float(count)
    sorted_pairs = sorted(deduped.items())
    return [p[0] for p in sorted_pairs], [p[1] for p in sorted_pairs]


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """A single result returned by :meth:`VectorStore.search`."""

    score: float
    repo_id: str
    file_path: str
    chunk_type: str
    start_line: int
    end_line: int
    qualified_name: str
    language: str
    content: str
    chunk_index: int


# ---------------------------------------------------------------------------
# RRF merge helper
# ---------------------------------------------------------------------------


def _rrf_merge(
    dense_hits: list[object],
    sparse_hits: list[object],
    top_k: int,
    k: int = 60,
) -> list[tuple[str, float, dict[str, object]]]:
    """Reciprocal Rank Fusion over two ranked hit lists.

    Returns up to *top_k* ``(point_id, rrf_score, payload)`` tuples sorted
    by descending score.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, object]] = {}

    for rank, hit in enumerate(dense_hits, 1):
        pid = str(hit.id)  # type: ignore[union-attr]
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        payloads[pid] = dict(hit.payload or {})  # type: ignore[union-attr]

    for rank, hit in enumerate(sparse_hits, 1):
        pid = str(hit.id)  # type: ignore[union-attr]
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        if pid not in payloads:
            payloads[pid] = dict(hit.payload or {})  # type: ignore[union-attr]

    top = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
    return [(pid, scores[pid], payloads[pid]) for pid in top]


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------


class VectorStore:
    """Qdrant-backed vector store with hybrid dense + sparse retrieval."""

    def __init__(
        self,
        host: str,
        port: int,
        embeddings_base_url: str,
        embeddings_api_key: str,
        embeddings_model: str,
    ) -> None:
        from openai import OpenAI  # noqa: PLC0415
        from qdrant_client import QdrantClient  # noqa: PLC0415

        self._client: QdrantClient = QdrantClient(host=host, port=port)
        self._embeddings: OpenAI = OpenAI(
            base_url=embeddings_base_url,
            api_key=embeddings_api_key,
        )
        self._model = embeddings_model

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def ensure_collection(self, vector_size: int) -> None:
        """Idempotently create the collection with dense + sparse vectors.

        Raises :class:`ValueError` if the collection already exists but its
        dense vector size does not match *vector_size*.
        """
        from qdrant_client.models import (  # noqa: PLC0415
            Distance,
            SparseIndexParams,
            SparseVectorParams,
            VectorParams,
        )

        existing = self._client.get_collections()
        names = {c.name for c in existing.collections}

        if COLLECTION_NAME in names:
            info = self._client.get_collection(COLLECTION_NAME)
            existing_size = info.config.params.vectors["dense"].size  # type: ignore[index]
            if existing_size != vector_size:
                raise ValueError(
                    f"Collection '{COLLECTION_NAME}' already exists with dense vector size "
                    f"{existing_size}, but current embeddings produce size {vector_size}. "
                    "Drop the collection manually or switch to a compatible embeddings model."
                )
            return

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": VectorParams(size=vector_size, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                ),
            },
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._embeddings.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert(self, chunks: list[CodeChunk], repo_id: str, batch_size: int = 64) -> None:
        """Embed *chunks* and upsert them into the Qdrant collection."""
        from qdrant_client.models import PointStruct, SparseVector  # noqa: PLC0415

        if not chunks:
            return

        # Embed in batches
        all_embeddings: list[list[float]] = []
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            all_embeddings.extend(self._embed([c.content for c in batch]))

        # Ensure collection exists (derive size from first embedding)
        self.ensure_collection(len(all_embeddings[0]))

        # Build and upsert points in batches
        for offset in range(0, len(chunks), batch_size):
            batch_chunks = chunks[offset : offset + batch_size]
            batch_embeddings = all_embeddings[offset : offset + batch_size]
            points: list[PointStruct] = []

            for chunk, dense_vec in zip(batch_chunks, batch_embeddings):
                key = f"{repo_id}:{chunk.entity.file_path}:{chunk.entity.qualified_name}:{chunk.chunk_index}"
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, key))

                sparse_indices, sparse_values = _sparse_vector(chunk.content)
                language = EXT_TO_LANG.get(
                    Path(chunk.entity.file_path).suffix.lower(), "unknown"
                )

                points.append(
                    PointStruct(
                        id=point_id,
                        vector={
                            "dense": dense_vec,
                            "sparse": SparseVector(
                                indices=sparse_indices,
                                values=sparse_values,
                            ),
                        },
                        payload={
                            "repo_id": repo_id,
                            "file_path": chunk.entity.file_path,
                            "chunk_type": chunk.entity.type,
                            "start_line": chunk.entity.start_line,
                            "end_line": chunk.entity.end_line,
                            "qualified_name": chunk.entity.qualified_name,
                            "chunk_index": chunk.chunk_index,
                            "chunk_total": chunk.chunk_total,
                            "language": language,
                            "content": chunk.content,
                        },
                    )
                )

            self._client.upsert(collection_name=COLLECTION_NAME, points=points)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        file_path: str | None = None,
        chunk_type: str | None = None,
        language: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid dense + sparse search over code chunks.

        Runs two separate searches (dense and sparse) and merges them with
        Reciprocal Rank Fusion.  Always filters by *repo_id*; optionally
        filters by *file_path*, *chunk_type*, and *language*.
        """
        from qdrant_client.models import (  # noqa: PLC0415
            FieldCondition,
            Filter,
            MatchValue,
            SparseVector,
        )

        # Embed query
        dense_vec = self._embed([query])[0]
        sparse_indices, sparse_values = _sparse_vector(query)

        # Build filter — repo_id is mandatory
        conditions = [FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        if file_path is not None:
            conditions.append(FieldCondition(key="file_path", match=MatchValue(value=file_path)))
        if chunk_type is not None:
            conditions.append(
                FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type))
            )
        if language is not None:
            conditions.append(FieldCondition(key="language", match=MatchValue(value=language)))

        qdrant_filter = Filter(must=conditions)
        fetch = top_k * 2

        # Dense search
        dense_response = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using="dense",
            query_filter=qdrant_filter,
            limit=fetch,
            with_payload=True,
        )

        # Sparse search
        sparse_response = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=SparseVector(indices=sparse_indices, values=sparse_values),
            using="sparse",
            query_filter=qdrant_filter,
            limit=fetch,
            with_payload=True,
        )

        # Reciprocal Rank Fusion
        merged = _rrf_merge(dense_response.points, sparse_response.points, top_k)

        return [
            SearchResult(
                score=score,
                repo_id=str(payload.get("repo_id", "")),
                file_path=str(payload.get("file_path", "")),
                chunk_type=str(payload.get("chunk_type", "")),
                start_line=int(payload.get("start_line", 0)),
                end_line=int(payload.get("end_line", 0)),
                qualified_name=str(payload.get("qualified_name", "")),
                language=str(payload.get("language", "")),
                content=str(payload.get("content", "")),
                chunk_index=int(payload.get("chunk_index", 0)),
            )
            for _pid, score, payload in merged
        ]


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_vector_store(settings: Settings | None = None) -> VectorStore:
    """Create a :class:`VectorStore` from application settings."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    return VectorStore(
        host=s.qdrant_host,
        port=s.qdrant_port,
        embeddings_base_url=s.embeddings_base_url,
        embeddings_api_key=s.embeddings_api_key,
        embeddings_model=s.embeddings_model,
    )
