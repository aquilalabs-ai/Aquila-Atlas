"""
PLAYGROUND — Phase 4.1 / Ingestion & Status
============================================
Demonstrates the full ingestion workflow via the REST API:
  POST /repos                   — submit an ingestion job
  GET  /repos/{id}/status       — poll until done (or failed)
  GET  /jobs/{job_id}           — look up a job by UUID
  GET  /repos                   — list all ingested repos
  GET  /repos/{id}/stats        — combined graph + vector stats

Prerequisites:
    docker compose up -d
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase4/02_ingest_and_status.py
"""

from __future__ import annotations

import os
import time

import httpx

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
INGEST_PATH = str(__import__("pathlib").Path(__file__).parents[2] / "aquila_atlas")
REPO_ID = "playground-full"
API_KEY = os.getenv("API_KEY", "")  # leave blank if auth is disabled

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)

# ──────────────────────────────────────────────
# 1. Submit ingestion job
# ──────────────────────────────────────────────
print("=" * 60)
print(f"POST /repos  (ingest {INGEST_PATH!r} → repo_id={REPO_ID!r})")
print("=" * 60)
resp = client.post("/repos", json={"path": INGEST_PATH, "repo_id": REPO_ID})
print(f"Status : {resp.status_code}")
if resp.status_code not in (200, 202):
    print(f"Error  : {resp.text}")
    client.close()
    raise SystemExit(1)
job = resp.json()
job_id = job["job_id"]
print(f"Job ID : {job_id}")
print(f"Body   : {job}")
print()

# ──────────────────────────────────────────────
# 2. Poll repo status until terminal state
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/status  (polling…)")
print("=" * 60)
for attempt in range(60):
    resp = client.get(f"/repos/{REPO_ID}/status")
    if resp.status_code == 404:
        print(f"  [{attempt:02d}] no job yet — waiting…")
        time.sleep(2)
        continue
    data = resp.json()
    status = data.get("status", "?")
    files = data.get("files")
    chunks = data.get("chunks")
    print(f"  [{attempt:02d}] status={status}  files={files}  chunks={chunks}")
    if status in ("done", "failed"):
        if status == "failed":
            print(f"  Error: {data.get('error')}")
        break
    time.sleep(2)
print()

# ──────────────────────────────────────────────
# 3. Look up the job by UUID
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /jobs/{job_id}")
print("=" * 60)
resp = client.get(f"/jobs/{job_id}")
print(f"Status : {resp.status_code}")
print(f"Body   : {resp.json()}")
print()

# ──────────────────────────────────────────────
# 4. List all repos
# ──────────────────────────────────────────────
print("=" * 60)
print("GET /repos")
print("=" * 60)
resp = client.get("/repos")
print(f"Status : {resp.status_code}")
data = resp.json()
print(f"Repos  : {data.get('repos')}  (total={data.get('total')})")
print()

# ──────────────────────────────────────────────
# 5. Repo stats
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/stats")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/stats")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    stats = resp.json()
    for k, v in stats.items():
        print(f"  {k:<20} {v}")
else:
    print(f"Body   : {resp.text}")
print()

client.close()
print("Done.")
