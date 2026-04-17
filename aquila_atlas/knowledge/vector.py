"""Qdrant vector store — hybrid dense + sparse search over code chunks."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aquila_atlas.ingestion.sources import EXT_TO_LANG

logger = logging.getLogger("aquila.vector")


if TYPE_CHECKING:
    from collections.abc import Sequence

    from openai import OpenAI
    from qdrant_client import QdrantClient
    from qdrant_client.models import ScoredPoint

    from aquila_atlas.config import Settings
    from aquila_atlas.ingestion.metadata import CodeChunk

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
    dense_hits: Sequence[ScoredPoint],
    sparse_hits: Sequence[ScoredPoint],
    top_k: int,
    k: int = 60,
) -> list[tuple[str, float, dict[str, Any]]]:
    """Reciprocal Rank Fusion over two ranked hit lists.

    Returns up to *top_k* ``(point_id, rrf_score, payload)`` tuples sorted
    by descending score.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(dense_hits, 1):
        pid = str(hit.id)
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        payloads[pid] = dict(hit.payload or {})

    for rank, hit in enumerate(sparse_hits, 1):
        pid = str(hit.id)
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
        if pid not in payloads:
            payloads[pid] = dict(hit.payload or {})

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

    def _embed(self, texts: list[str], _retries: int = 3) -> list[list[float]]:
        """Embed *texts* with retry on transient connection errors (e.g. Ollama OOM reset)."""
        last_exc: Exception | None = None
        for attempt in range(_retries):
            try:
                response = self._embeddings.embeddings.create(model=self._model, input=texts)
                return [item.embedding for item in response.data]
            except Exception as exc:
                last_exc = exc
                if attempt < _retries - 1:
                    wait = 2**attempt  # 1s, 2s, 4s …
                    logger.warning(
                        "embed attempt %d/%d failed (%s) — retrying in %ds",
                        attempt + 1,
                        _retries,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
        raise RuntimeError(f"Embedding failed after {_retries} attempts") from last_exc

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert(self, chunks: list[CodeChunk], repo_id: str, batch_size: int = 25) -> None:
        """Embed *chunks* and upsert them into the Qdrant collection."""
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
            points = [
                self._build_point(chunk, dense_vec, repo_id)
                for chunk, dense_vec in zip(batch_chunks, batch_embeddings, strict=True)
            ]
            self._client.upsert(collection_name=COLLECTION_NAME, points=points)

    def _build_point(self, chunk: CodeChunk, dense_vec: list[float], repo_id: str) -> Any:
        """Construct a Qdrant PointStruct for a single chunk."""
        from qdrant_client.models import PointStruct, SparseVector  # noqa: PLC0415

        key = (
            f"{repo_id}:{chunk.entity.file_path}:{chunk.entity.qualified_name}:{chunk.chunk_index}"
        )
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, key))
        sparse_indices, sparse_values = _sparse_vector(chunk.content)
        language = EXT_TO_LANG.get(Path(chunk.entity.file_path).suffix.lower(), "unknown")

        return PointStruct(
            id=point_id,
            vector={
                "dense": dense_vec,
                "sparse": SparseVector(indices=sparse_indices, values=sparse_values),
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

    # ------------------------------------------------------------------
    # Repo listing
    # ------------------------------------------------------------------

    def get_repo_stats(self, repo_id: str) -> dict[str, int]:
        """Return chunk count, file count, and entity-type breakdown for *repo_id*."""
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return {"chunks": 0, "files": 0}

        from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: PLC0415

        qdrant_filter = Filter(
            must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        )
        count_result = self._client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qdrant_filter,
            exact=True,
        )
        total_chunks = count_result.count

        files: set[str] = set()
        type_counts: dict[str, int] = {}
        offset = None
        while True:
            result, next_offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                with_payload=["file_path", "chunk_type"],
                limit=256,
                offset=offset,
            )
            for point in result:
                if point.payload:
                    files.add(str(point.payload.get("file_path", "")))
                    ct = str(point.payload.get("chunk_type", "unknown"))
                    type_counts[ct] = type_counts.get(ct, 0) + 1
            if next_offset is None:
                break
            offset = next_offset

        return {"chunks": total_chunks, "files": len(files), **type_counts}

    def list_files(self, repo_id: str) -> list[str]:
        """Return all unique file paths ingested for *repo_id*, sorted."""
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return []

        from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: PLC0415

        qdrant_filter = Filter(
            must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        )
        file_paths: set[str] = set()
        offset = None
        while True:
            result, next_offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                with_payload=["file_path"],
                limit=256,
                offset=offset,
            )
            for point in result:
                if point.payload and "file_path" in point.payload:
                    file_paths.add(str(point.payload["file_path"]))
            if next_offset is None:
                break
            offset = next_offset

        return sorted(file_paths)

    def get_file_chunks(self, repo_id: str, file_path: str) -> list[dict[str, Any]]:
        """Return all chunk payloads for a specific file, ordered by start_line."""
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return []

        from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: PLC0415

        qdrant_filter = Filter(
            must=[
                FieldCondition(key="repo_id", match=MatchValue(value=repo_id)),
                FieldCondition(key="file_path", match=MatchValue(value=file_path)),
            ]
        )
        chunks: list[dict[str, Any]] = []
        offset = None
        while True:
            result, next_offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                with_payload=True,
                limit=256,
                offset=offset,
            )
            for point in result:
                if point.payload:
                    chunks.append(dict(point.payload))
            if next_offset is None:
                break
            offset = next_offset

        return sorted(chunks, key=lambda c: int(c.get("start_line", 0)))

    def delete_files(self, repo_id: str, file_paths: list[str]) -> int:
        """Delete all points for the given *file_paths* within *repo_id*.

        Returns the number of points deleted.
        """
        if not file_paths:
            return 0
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return 0

        from qdrant_client.models import (  # noqa: PLC0415
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        qdrant_filter = Filter(
            must=[
                FieldCondition(key="repo_id", match=MatchValue(value=repo_id)),
                FieldCondition(key="file_path", match=MatchAny(any=file_paths)),
            ]
        )
        count_before = self._client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qdrant_filter,
            exact=True,
        ).count
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qdrant_filter,
        )
        return count_before

    def delete_repo(self, repo_id: str) -> int:
        """Delete all points for *repo_id* from the collection.

        Returns the number of points deleted.
        """
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return 0

        from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: PLC0415

        qdrant_filter = Filter(
            must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        )
        count_before = self._client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qdrant_filter,
            exact=True,
        ).count
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qdrant_filter,
        )
        return count_before

    def list_repo_ids(self) -> list[str]:
        """Return all repository IDs present in the collection, sorted."""
        collections = {c.name for c in self._client.get_collections().collections}
        if COLLECTION_NAME not in collections:
            return []

        repo_ids: set[str] = set()
        offset = None
        while True:
            result, next_offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
                with_payload=["repo_id"],
                limit=256,
                offset=offset,
            )
            for point in result:
                if point.payload and "repo_id" in point.payload:
                    repo_ids.add(str(point.payload["repo_id"]))
            if next_offset is None:
                break
            offset = next_offset

        return sorted(repo_ids)

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
        conditions: list[Any] = [FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        if file_path is not None:
            conditions.append(FieldCondition(key="file_path", match=MatchValue(value=file_path)))
        if chunk_type is not None:
            conditions.append(FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type)))
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
