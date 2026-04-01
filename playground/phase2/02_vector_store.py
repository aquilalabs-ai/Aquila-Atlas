"""
PLAYGROUND — Phase 2 / Vector Store (Qdrant)
=============================================
Demonstrates embedding and hybrid search:
  1. Parse + chunk a local folder
  2. Upsert chunks into Qdrant (dense + sparse vectors)
  3. Run hybrid search queries and inspect results

Prerequisites:
    docker compose up -d             (starts Qdrant on localhost:6333)
    Ollama running with nomic-embed-text pulled  — OR —
    set EMBEDDINGS_BASE_URL / EMBEDDINGS_API_KEY / EMBEDDINGS_MODEL in .env

Run:
    uv run python playground/phase2/02_vector_store.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, chunk_files
from aquila_atlas.knowledge import get_vector_store

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
TARGET  = "aquila_atlas/ingestion"
REPO_ID = "playground-ingestion"
QUERY   = "how are imports extracted from a Python file"

# ──────────────────────────────────────────────
# 1. Chunk the folder
# ──────────────────────────────────────────────
loader = LocalFolderLoader(TARGET)
files  = list(loader.load())
chunks = list(chunk_files(files))

print(f"Chunks to embed: {len(chunks)}")
total_tokens = sum(c.token_count for c in chunks)
print(f"Total tokens   : {total_tokens}\n")

# ──────────────────────────────────────────────
# 2. Upsert into Qdrant
# ──────────────────────────────────────────────
print("Upserting into Qdrant…")
with get_vector_store() as store:
    store.upsert(chunks, repo_id=REPO_ID)
    print("Upsert complete.\n")

    # ──────────────────────────────────────────
    # 3. Hybrid search — no filter
    # ──────────────────────────────────────────
    print(f'Search: "{QUERY}"')
    print("-" * 60)
    results = store.search(QUERY, repo_id=REPO_ID, top_k=5)
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r.score:.4f}  {r.file_path}:{r.start_line}-{r.end_line}  ({r.chunk_type})")
        print(f"     {r.qualified_name}")
        preview = r.content[:150].replace("\n", " ")
        print(f"     {preview}…\n")

    # ──────────────────────────────────────────
    # 4. Filtered search — functions only
    # ──────────────────────────────────────────
    print("-" * 60)
    print('Same query filtered to chunk_type=function:')
    results_fn = store.search(QUERY, repo_id=REPO_ID, top_k=5, chunk_type="function")
    for i, r in enumerate(results_fn, 1):
        print(f"[{i}] score={r.score:.4f}  {r.qualified_name}  ({r.file_path}:{r.start_line})")

    # ──────────────────────────────────────────
    # 5. Language filter
    # ──────────────────────────────────────────
    print("\n" + "-" * 40)
    print("Same query filtered to language=Python:")
    results_py = store.search(QUERY, repo_id=REPO_ID, top_k=5, language="Python")
    for i, r in enumerate(results_py, 1):
        print(f"[{i}] [{r.language}]  {r.qualified_name}  score={r.score:.4f}")

print("\nDone.")
