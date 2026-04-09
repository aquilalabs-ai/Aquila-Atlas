"""
PLAYGROUND — Phase 5 / Skip Extensions
=======================================
Shows the effect of extension filtering on which files get documented.
Runs two per_file jobs side-by-side:
  1. No filter  (backend defaults apply)
  2. Explicit filter (only code files — skips media, data, compiled, etc.)

Compare file counts and which files were included/excluded.

Prerequisites:
    docker compose up -d
    Data already ingested
    uv run aquila serve

Run:
    uv run python playground/phase5/03_skip_extensions.py
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

# Extensions to skip in the "filtered" run
SKIP_MEDIA    = [".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
                 ".mp4", ".mp3", ".wav", ".ogg", ".flac"]
SKIP_COMPILED = [".pyc", ".pyo", ".pyd", ".class", ".jar", ".so", ".dll",
                 ".exe", ".wasm", ".rlib"]
SKIP_DATA     = [".csv", ".parquet", ".pkl", ".pickle", ".json", ".yaml",
                 ".yml", ".xml", ".db", ".sqlite", ".npy", ".npz", ".log"]
SKIP_ARCHIVES = [".tar", ".zip", ".gz", ".bz2", ".xz", ".7z", ".rar"]
SKIP_LOCKS    = [".lock"]
SKIP_DOCS     = [".md", ".rst", ".txt"]

ALL_SKIP = SKIP_MEDIA + SKIP_COMPILED + SKIP_DATA + SKIP_ARCHIVES + SKIP_LOCKS + SKIP_DOCS

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client  = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)


def submit_and_wait(label: str, exclude_extensions: list[str] | None) -> list[str]:
    print(f"\n{'=' * 60}")
    print(f"Run: {label}")
    if exclude_extensions is None:
        print("  exclude_extensions: None (backend defaults)")
    else:
        print(f"  exclude_extensions: {len(exclude_extensions)} extensions")
    print("=" * 60)

    payload: dict[str, object] = {
        "scope": "per_file",
        "style": "technical",
        "language": "en",
    }
    if exclude_extensions is not None:
        payload["exclude_extensions"] = exclude_extensions

    resp = client.post(f"/repos/{REPO_ID}/docs/generate", json=payload)
    if resp.status_code not in (200, 202):
        print(f"  Submit failed: {resp.status_code} {resp.text}")
        return []
    job_id = resp.json()["job_id"]
    print(f"  job_id={job_id}")

    for _ in range(300):
        resp = client.get(f"/repos/{REPO_ID}/docs/jobs/{job_id}")
        if resp.status_code != 200:
            print(f"  Poll error: {resp.status_code}")
            return []
        data   = resp.json()
        status = data.get("status")
        done   = data.get("completed", 0)
        total  = data.get("total", 0)
        print(f"  {status:8}  {done}/{total if total else '?'}", end="\r")
        if status == "done":
            print()
            return sorted(data.get("files", []))
        if status == "failed":
            print(f"\n  Failed: {data.get('error')}")
            return []
        time.sleep(2)

    print("\n  Timeout")
    return []


files_default  = submit_and_wait("No filter (backend defaults)", None)
files_filtered = submit_and_wait("Explicit filter (all presets)", ALL_SKIP)

# ──────────────────────────────────────────────
# Comparison
# ──────────────────────────────────────────────
print(f"\n{'=' * 60}")
print("Comparison")
print("=" * 60)
print(f"  Default filter  : {len(files_default)} files")
print(f"  Explicit filter : {len(files_filtered)} files")

only_in_default = sorted(set(files_default) - set(files_filtered))
only_in_filtered = sorted(set(files_filtered) - set(files_default))

if only_in_default:
    print(f"\n  Files in default but NOT in explicit ({len(only_in_default)}):")
    for f in only_in_default[:20]:
        print(f"    - {f}")
    if len(only_in_default) > 20:
        print(f"    … and {len(only_in_default) - 20} more")

if only_in_filtered:
    print(f"\n  Files in explicit but NOT in default ({len(only_in_filtered)}):")
    for f in only_in_filtered[:20]:
        print(f"    - {f}")

client.close()
print("\nDone.")
