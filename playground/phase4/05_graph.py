"""
PLAYGROUND — Phase 4.1 / Graph Endpoints
=========================================
Exercises the Neo4j knowledge graph endpoints:
  GET  /repos/{id}/graph/stats    — per-label node counts + relationship count
  GET  /repos/{id}/graph          — full node + edge list
  POST /repos/{id}/graph/query    — arbitrary read-only Cypher

Prerequisites:
    docker compose up -d
    Data already ingested (run 02_ingest_and_status.py first)
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase4/05_graph.py
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

# ──────────────────────────────────────────────
# 1. Graph stats
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/graph/stats")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/graph/stats")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Relationships : {data.get('relationship_count')}")
    print("Node counts:")
    for label, count in data.get("node_counts", {}).items():
        print(f"  {label:<15} {count}")
else:
    print(f"Error : {resp.text}")
print()

# ──────────────────────────────────────────────
# 2. Full graph snapshot (truncated output)
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/graph  (first 5 nodes + 5 edges shown)")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/graph")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    print(f"node_count={data.get('node_count')}  edge_count={data.get('edge_count')}")
    print("\nSample nodes:")
    for n in nodes[:5]:
        props = n.get("properties", {})
        name = props.get("name") or props.get("path") or n.get("id", "")
        print(f"  [{n['label']}] {name}")
    print("\nSample edges:")
    for e in edges[:5]:
        print(f"  {e.get('source')}  --{e.get('type')}-->  {e.get('target')}")
else:
    print(f"Error : {resp.text}")
print()

# ──────────────────────────────────────────────
# 3. Cypher queries
# ──────────────────────────────────────────────


def _cypher(label: str, cypher: str, params: dict | None = None) -> None:
    print("=" * 60)
    print(label)
    print("=" * 60)
    resp = client.post(
        f"/repos/{REPO_ID}/graph/query",
        json={"cypher": cypher, "params": params or {}},
    )
    print(f"Status : {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        rows = data.get("rows", [])
        print(f"Rows   : {data.get('total')}")
        for row in rows[:10]:
            print(f"  {row}")
        if len(rows) > 10:
            print(f"  … ({len(rows) - 10} more rows)")
    else:
        print(f"Error  : {resp.text}")
    print()


# 3a. All functions in the repo
_cypher(
    "Cypher 1 — all functions (first 10)",
    "MATCH (f:Function {repo_id: $repo_id}) "
    "RETURN f.name AS name, f.file_path AS file "
    "ORDER BY f.name LIMIT 10",
    {"repo_id": REPO_ID},
)

# 3b. Call graph — which functions call which
_cypher(
    "Cypher 2 — call graph edges",
    "MATCH (a)-[:CALLS]->(b) "
    "WHERE a.repo_id = $repo_id "
    "RETURN a.name AS caller, b.name AS callee "
    "LIMIT 10",
    {"repo_id": REPO_ID},
)

# 3c. Files with the most defined entities
_cypher(
    "Cypher 3 — files by entity count",
    "MATCH (f:File {repo_id: $repo_id})-[:DEFINES]->(e) "
    "RETURN f.path AS file, count(e) AS entities "
    "ORDER BY entities DESC LIMIT 10",
    {"repo_id": REPO_ID},
)

client.close()
print("Done.")
