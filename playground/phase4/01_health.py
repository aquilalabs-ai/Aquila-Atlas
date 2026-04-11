"""
PLAYGROUND — Phase 4.1 / Health Probes
=======================================
Exercises the two health endpoints:
  GET /health       — liveness probe
  GET /health/ready — readiness probe (checks Neo4j + Qdrant)

Prerequisites:
    docker compose up -d
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase4/01_health.py
"""

from __future__ import annotations

import httpx

# ──────────────────────────────────────────────
# Config — change if your server runs elsewhere
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"

client = httpx.Client(base_url=BASE_URL, timeout=10)

# ──────────────────────────────────────────────
# 1. Liveness
# ──────────────────────────────────────────────
print("=" * 60)
print("GET /health  (liveness)")
print("=" * 60)
resp = client.get("/health")
print(f"Status : {resp.status_code}")
print(f"Body   : {resp.json()}")
print()

# ──────────────────────────────────────────────
# 2. Readiness
# ──────────────────────────────────────────────
print("=" * 60)
print("GET /health/ready  (readiness — checks Neo4j + Qdrant)")
print("=" * 60)
resp = client.get("/health/ready")
print(f"Status : {resp.status_code}")
data = resp.json()
print(f"Body   : {data}")
if data.get("status") == "ready":
    print("All backing services reachable.")
else:
    neo4j_ok = data.get("neo4j", False)
    qdrant_ok = data.get("qdrant", False)
    if not neo4j_ok:
        print("  Neo4j is NOT reachable — is docker compose up?")
    if not qdrant_ok:
        print("  Qdrant is NOT reachable — is docker compose up?")
print()

client.close()
print("Done.")
