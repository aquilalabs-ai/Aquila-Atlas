"""
PLAYGROUND — Phase 5 / Scope Comparison
========================================
Generates docs with all five scopes in sequence and prints a summary
of how many files each scope produces and how long each takes.

  Scopes: architecture | per_module | per_file | subsystem | flows

Prerequisites:
    docker compose up -d
    Data already ingested (run playground/phase4/02_ingest_and_status.py first)
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase5/02_scopes.py
"""

from __future__ import annotations

import os
import time

import httpx

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REPO_ID  = "playground-full"
API_KEY  = os.getenv("API_KEY", "")
STYLE    = "technical"
LANGUAGE = "en"
SCOPES   = ["architecture", "per_module", "per_file", "subsystem", "flows"]

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client  = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)

results: list[dict[str, object]] = []

for scope in SCOPES:
    print(f"\n{'=' * 60}")
    print(f"Scope: {scope}")
    print("=" * 60)

    # Submit
    resp = client.post(
        f"/repos/{REPO_ID}/docs/generate",
        json={"scope": scope, "style": STYLE, "language": LANGUAGE},
    )
    if resp.status_code not in (200, 202):
        print(f"  Submit failed: {resp.status_code} {resp.text}")
        results.append({"scope": scope, "status": "submit_failed", "files": 0, "elapsed": 0})
        continue
    job_id  = resp.json()["job_id"]
    start   = time.time()
    print(f"  job_id={job_id}")

    # Poll
    final_status = "timeout"
    for _ in range(300):
        resp = client.get(f"/repos/{REPO_ID}/docs/jobs/{job_id}")
        if resp.status_code != 200:
            final_status = f"poll_error_{resp.status_code}"
            break
        data   = resp.json()
        status = data.get("status", "?")
        done   = data.get("completed", 0)
        total  = data.get("total", 0)
        target = data.get("current_target") or ""
        print(f"  {status:8}  {done}/{total if total else '?'}  {target}", end="\r")
        if status == "done":
            final_status = "done"
            break
        if status == "failed":
            final_status = f"failed: {data.get('error', '?')}"
            break
        time.sleep(2)
    print()  # clear \r line

    elapsed   = time.time() - start
    file_list = data.get("files", []) if final_status == "done" else []
    results.append({
        "scope":   scope,
        "status":  final_status,
        "files":   len(file_list),
        "elapsed": round(elapsed, 1),
        "job_id":  job_id,
    })

    if final_status == "done":
        print(f"  Done in {elapsed:.1f}s — {len(file_list)} files: {file_list[:5]}{'…' if len(file_list) > 5 else ''}")

# ──────────────────────────────────────────────
# Summary table
# ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"{'Scope':<16} {'Status':<12} {'Files':>6} {'Time (s)':>10}")
print("-" * 60)
for r in results:
    print(f"{r['scope']:<16} {str(r['status']):<12} {r['files']:>6} {r['elapsed']:>10}")
print("=" * 60)

client.close()
print("\nDone.")
