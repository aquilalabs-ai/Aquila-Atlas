"""
PLAYGROUND — Phase 5 / Generate & Poll
=======================================
Submits a documentation generation job and polls until done:
  POST /repos/{id}/docs/generate          — submit job
  GET  /repos/{id}/docs/jobs/{job_id}     — poll status + progress
  GET  /repos/{id}/docs/{job_id}          — fetch content when done

Prerequisites:
    docker compose up -d
    Data already ingested (run playground/phase4/02_ingest_and_status.py first)
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase5/01_generate_and_poll.py
"""

from __future__ import annotations

import os
import time

import httpx

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REPO_ID = "playground-full"
API_KEY = os.getenv("API_KEY", "")

# Scope:    "architecture" | "per_module" | "per_file" | "subsystem" | "flows"
# Style:    "technical" | "functional"
# Language: "en" | "fr" | "es" | "de" | "zh" | "ja" | "pt" | "ar"
SCOPE = "per_module"
STYLE = "technical"
LANGUAGE = "en"

# Extensions to skip (None = use backend defaults)
EXCLUDE_EXTENSIONS: list[str] | None = None

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)

# ──────────────────────────────────────────────
# 1. Submit job
# ──────────────────────────────────────────────
print("=" * 60)
print(f"POST /repos/{REPO_ID}/docs/generate")
print(f"  scope={SCOPE!r}  style={STYLE!r}  language={LANGUAGE!r}")
print("=" * 60)

payload: dict[str, object] = {"scope": SCOPE, "style": STYLE, "language": LANGUAGE}
if EXCLUDE_EXTENSIONS is not None:
    payload["exclude_extensions"] = EXCLUDE_EXTENSIONS

resp = client.post(f"/repos/{REPO_ID}/docs/generate", json=payload)
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
# 2. Poll until done
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/docs/jobs/{job_id}  (polling…)")
print("=" * 60)

for attempt in range(300):  # up to 10 minutes (2 s interval)
    resp = client.get(f"/repos/{REPO_ID}/docs/jobs/{job_id}")
    if resp.status_code != 200:
        print(f"  [{attempt:03d}] HTTP {resp.status_code} — {resp.text}")
        break
    data = resp.json()
    status = data.get("status", "?")
    done = data.get("completed", 0)
    total = data.get("total", 0)
    target = data.get("current_target") or ""
    pct = f"{done}/{total}" if total else "…"
    print(f"  [{attempt:03d}] {status:8}  {pct:>8}  {target}")
    if status == "done":
        print(f"\n  Files: {data.get('files', [])}")
        break
    if status == "failed":
        print(f"\n  Error: {data.get('error')}")
        client.close()
        raise SystemExit(1)
    time.sleep(2)
print()

# ──────────────────────────────────────────────
# 3. Fetch content
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/docs/{job_id}  (content)")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/docs/{job_id}")
print(f"Status : {resp.status_code}")
if resp.status_code == 200:
    content = resp.json()
    files = content.get("files", {})
    print(f"Files  : {sorted(files.keys())}")
    if files:
        first_name = sorted(files.keys())[0]
        first_text = files[first_name]
        preview = first_text[:400].replace("\n", "↵ ")
        print(f"\nPreview of {first_name!r}:")
        print(f"  {preview}{'…' if len(first_text) > 400 else ''}")
else:
    print(f"Body   : {resp.text}")
print()

client.close()
print("Done.")
