"""
PLAYGROUND — Phase 5 / Download ZIP
=====================================
Downloads the documentation ZIP for a completed job and inspects its contents:
  GET /repos/{id}/docs/{job_id}/download-zip

Shows the archive structure (matching the two-layer layout):
  index.html          ← navigation shell
  files/
    *.html            ← converted doc pages

Prerequisites:
    docker compose up -d
    At least one completed doc job (run 01_generate_and_poll.py first)
    uv run aquila serve

Run:
    uv run python playground/phase5/05_download_zip.py
"""

from __future__ import annotations

import io
import os
import zipfile

import httpx

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REPO_ID = "playground-full"
API_KEY = os.getenv("API_KEY", "")

# Set JOB_ID to a known job_id, or leave empty to use the most recently saved doc
JOB_ID: str = os.getenv("DOC_JOB_ID", "")

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=60)

# ──────────────────────────────────────────────
# Resolve job_id if not provided
# ──────────────────────────────────────────────
if not JOB_ID:
    print("No JOB_ID set — looking up most recent saved doc…")
    resp = client.get(f"/repos/{REPO_ID}/docs")
    if resp.status_code != 200 or not resp.json().get("docs"):
        print("No saved docs found. Run 01_generate_and_poll.py first.")
        client.close()
        raise SystemExit(1)
    JOB_ID = resp.json()["docs"][0]["job_id"]
    print(f"  Using job_id={JOB_ID}")

# ──────────────────────────────────────────────
# 1. Download ZIP
# ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"GET /repos/{REPO_ID}/docs/{JOB_ID[:8]}…/download-zip")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/docs/{JOB_ID}/download-zip")
print(f"Status       : {resp.status_code}")
if resp.status_code != 200:
    print(f"Error        : {resp.text}")
    client.close()
    raise SystemExit(1)

content_disp = resp.headers.get("content-disposition", "")
content_type = resp.headers.get("content-type", "")
size_kb = len(resp.content) / 1024
print(f"Content-Type : {content_type}")
print(f"Disposition  : {content_disp}")
print(f"Size         : {size_kb:.1f} KB")
print()

# ──────────────────────────────────────────────
# 2. Inspect ZIP structure
# ──────────────────────────────────────────────
buf = io.BytesIO(resp.content)
with zipfile.ZipFile(buf, "r") as zf:
    names = sorted(zf.namelist())
    print(f"Archive contains {len(names)} entries:")
    print()

    # Categorise
    root_files = [n for n in names if "/" not in n]
    nested_files = [n for n in names if "/" in n]

    print("Root files:")
    for n in root_files:
        info = zf.getinfo(n)
        print(f"  {n:<40} ({info.file_size:>8} bytes)")

    print(f"\nfiles/ directory ({len(nested_files)} entries):")
    for n in nested_files[:20]:
        info = zf.getinfo(n)
        print(f"  {n:<40} ({info.file_size:>8} bytes)")
    if len(nested_files) > 20:
        print(f"  … and {len(nested_files) - 20} more")

    # Preview index.html if present
    if "index.html" in names:
        print(f"\n{'=' * 60}")
        print("index.html preview (first 600 bytes):")
        print("=" * 60)
        text = zf.read("index.html").decode("utf-8", errors="replace")
        print(text[:600])
        print("…" if len(text) > 600 else "")

print()
client.close()
print("Done.")
