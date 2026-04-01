"""
PLAYGROUND — Phase 1 / Parser
================================
Explore how a source file gets parsed into CodeEntity objects.

Run:
    uv run python playground/phase1/02_parser.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, parse

# ──────────────────────────────────────────────
# Pick the file to inspect
# ──────────────────────────────────────────────
TARGET_FILE = "parser.py"

loader = LocalFolderLoader("aquila_atlas/ingestion")
files = {f.path: f for f in loader.load()}

raw = files.get(TARGET_FILE)
if raw is None:
    available = "\n  ".join(files)
    raise SystemExit(f"File not found. Available:\n  {available}")

# ──────────────────────────────────────────────
# Parse → entities
# ──────────────────────────────────────────────
entities = parse(raw)

print(f"Parsed: {TARGET_FILE}")
print(f"Entities found: {len(entities)}\n")

# Summary table
print(f"{'TYPE':<10} {'QUALIFIED NAME':<45} {'LINES':<12} {'VIS':<10} {'ASYNC'}")
print("-" * 90)
for e in entities:
    lines = f"{e.start_line}–{e.end_line}"
    async_tag = "yes" if e.is_async else ""
    print(f"{e.type:<10} {e.qualified_name:<45} {lines:<12} {e.visibility:<10} {async_tag}")

# ──────────────────────────────────────────────
# Drill into one entity
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("DRILL-DOWN: first function entity")
print("=" * 60)

fn = next((e for e in entities if e.type == "function"), None)
if fn:
    print(f"Name       : {fn.name}")
    print(f"Qualified  : {fn.qualified_name}")
    print(f"Lines      : {fn.start_line}–{fn.end_line}")
    print(f"Visibility : {fn.visibility}")
    print(f"Async      : {fn.is_async}")
    print(f"Decorators : {fn.decorators}")
    print(f"Docstring  : {fn.docstring!r}")
    print(f"\nSource:\n{fn.source}")

# ──────────────────────────────────────────────
# Imports on the file entity
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("FILE-LEVEL IMPORTS")
print("=" * 60)

file_entity = next(e for e in entities if e.type == "file")
for imp in file_entity.imports:
    print(f"  {imp}")
