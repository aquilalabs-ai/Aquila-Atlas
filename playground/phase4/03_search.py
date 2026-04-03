"""
PLAYGROUND — Phase 4.1 / Semantic Search
=========================================
Exercises the hybrid search endpoint:
  GET /repos/{id}/search

Runs several queries with different filters to show how RRF merges
dense-vector and sparse-BM25 results.

Prerequisites:
    docker compose up -d
    Data already ingested (run 02_ingest_and_status.py first)
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase4/03_search.py
"""

from __future__ import annotations

import os

import httpx

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REPO_ID = "playground-full"
API_KEY = os.getenv("API_KEY", "")

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)


def _print_results(label: str, resp: httpx.Response) -> None:
    print(f"\n{'=' * 60}")
    print(label)
    print("=" * 60)
    print(f"Status : {resp.status_code}")
    if resp.status_code != 200:
        print(f"Error  : {resp.text}")
        return
    data = resp.json()
    results = data.get("results", [])
    print(f"Total  : {data.get('total', 0)} results")
    for i, r in enumerate(results[:5], 1):
        score = r.get("score", 0.0)
        path = r.get("file_path", "")
        lines = f"{r.get('start_line')}–{r.get('end_line')}"
        name = r.get("qualified_name", "")
        lang = r.get("language", "")
        print(f"  [{i}] score={score:.4f}  {path}:{lines}  {name}  ({lang})")


# ──────────────────────────────────────────────
# 1. Broad free-text search
# ──────────────────────────────────────────────
resp = client.get(
    f"/repos/{REPO_ID}/search",
    params={"q": "how is token-aware chunking implemented", "top_k": 5},
)
_print_results("1. Broad search — token-aware chunking", resp)

# ──────────────────────────────────────────────
# 2. Filter by chunk type
# ──────────────────────────────────────────────
resp = client.get(
    f"/repos/{REPO_ID}/search",
    params={"q": "embed text batch", "top_k": 5, "chunk_type": "function"},
)
_print_results("2. chunk_type=function — embed text batch", resp)

# ──────────────────────────────────────────────
# 3. Filter by language
# ──────────────────────────────────────────────
resp = client.get(
    f"/repos/{REPO_ID}/search",
    params={"q": "graph cypher query", "top_k": 5, "language": "Python"},
)
_print_results("3. language=Python — graph cypher query", resp)

# ──────────────────────────────────────────────
# 4. Filter by file
# ──────────────────────────────────────────────
resp = client.get(
    f"/repos/{REPO_ID}/search",
    params={"q": "sparse vector BM25", "top_k": 5, "file": "knowledge/vector.py"},
)
_print_results("4. file=knowledge/vector.py — sparse vector BM25", resp)

# ──────────────────────────────────────────────
# 5. File listing for the repo
# ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"GET /repos/{REPO_ID}/files")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/files")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    files = data.get("files", [])
    print(f"Total  : {data.get('total')} files")
    for f in files[:10]:
        print(f"  {f}")
    if len(files) > 10:
        print(f"  … ({len(files) - 10} more)")
print()

client.close()
print("Done.")
