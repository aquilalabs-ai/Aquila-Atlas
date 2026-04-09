"""
PLAYGROUND — Phase 5 / Saved Docs (DB persistence)
===================================================
Exercises the documentation persistence endpoints:
  GET    /repos/{id}/docs                — list saved docs (metadata)
  GET    /repos/{id}/docs/{job_id}       — fetch full content from DB
  DELETE /repos/{id}/docs/{job_id}       — delete a saved doc

Also demonstrates the cancel endpoint:
  POST   /repos/{id}/docs/jobs/{job_id}/cancel

Prerequisites:
    docker compose up -d
    At least one completed doc job (run 01_generate_and_poll.py first)
    uv run aquila serve

Run:
    uv run python playground/phase5/04_saved_docs.py
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

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client  = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)

# ──────────────────────────────────────────────
# 1. List saved docs
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/docs  (list saved docs)")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/docs")
print(f"Status : {resp.status_code}")
data = resp.json()
docs = data.get("docs", [])
print(f"Total  : {data.get('total', 0)}")
print()
for doc in docs:
    print(
        f"  job_id={doc['job_id'][:8]}…  "
        f"scope={doc['scope']:<12}  "
        f"style={doc['style']:<12}  "
        f"lang={doc['language']:<4}  "
        f"created={doc.get('created_at', '?')}"
    )

if not docs:
    print("  No saved docs found. Run 01_generate_and_poll.py first to create one.")
    client.close()
    raise SystemExit(0)

# ──────────────────────────────────────────────
# 2. Load full content for the most recent doc
# ──────────────────────────────────────────────
latest = docs[0]
job_id = latest["job_id"]
print(f"\n{'=' * 60}")
print(f"GET /repos/{REPO_ID}/docs/{job_id[:8]}…  (full content)")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/docs/{job_id}")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    content = resp.json()
    files   = content.get("files", {})
    print(f"Files  : {sorted(files.keys())}")
    if files:
        name    = sorted(files.keys())[0]
        text    = files[name]
        preview = text[:500].replace("\n", "↵ ")
        print(f"\nPreview of {name!r}:")
        print(f"  {preview}{'…' if len(text) > 500 else ''}")
else:
    print(f"Body   : {resp.text}")

# ──────────────────────────────────────────────
# 3. Demonstrate cancel on a fresh job
# ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print("Cancel demo — submit a job and immediately cancel it")
print("=" * 60)
resp = client.post(
    f"/repos/{REPO_ID}/docs/generate",
    json={"scope": "per_file", "style": "technical", "language": "en"},
)
if resp.status_code in (200, 202):
    new_job_id = resp.json()["job_id"]
    print(f"  Submitted job_id={new_job_id}")
    time.sleep(0.5)  # let the job start
    resp = client.post(f"/repos/{REPO_ID}/docs/jobs/{new_job_id}/cancel")
    print(f"  Cancel status : {resp.status_code}")
    print(f"  Body          : {resp.json()}")
    # Poll once to confirm it transitions to failed
    time.sleep(3)
    resp = client.get(f"/repos/{REPO_ID}/docs/jobs/{new_job_id}")
    if resp.status_code == 200:
        print(f"  Final status  : {resp.json().get('status')}")
else:
    print(f"  Could not submit: {resp.status_code} {resp.text}")

# ──────────────────────────────────────────────
# 4. Delete the oldest saved doc (if >1 exist)
# ──────────────────────────────────────────────
if len(docs) > 1:
    oldest = docs[-1]
    del_id = oldest["job_id"]
    print(f"\n{'=' * 60}")
    print(f"DELETE /repos/{REPO_ID}/docs/{del_id[:8]}…")
    print("=" * 60)
    resp = client.delete(f"/repos/{REPO_ID}/docs/{del_id}")
    print(f"Status : {resp.status_code}")
    print(f"Body   : {resp.json()}")
else:
    print("\n(Skipping delete — only one saved doc exists, keeping it)")

print()
client.close()
print("Done.")
