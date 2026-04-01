"""
PLAYGROUND — Phase 2 / Call Graph Analysis
===========================================
Demonstrates best-effort static call graph resolution:
  1. Parse a folder and extract call triples
  2. Show caller → callee relationships before ingestion
  3. Ingest and query callers/callees from Neo4j

Prerequisites:
    docker compose up -d

Run:
    uv run python playground/phase2/03_call_graph.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, parse
from aquila_atlas.knowledge import extract_calls, get_graph_store

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
TARGET  = "aquila_atlas/ingestion"
REPO_ID = "playground-callgraph"

# ──────────────────────────────────────────────
# 1. Parse and extract raw call triples
# ──────────────────────────────────────────────
loader = LocalFolderLoader(TARGET)
files  = list(loader.load())

all_entities = []
for f in files:
    all_entities.extend(parse(f))

callables = [e for e in all_entities if e.type in ("function", "method")]
call_triples = extract_calls(callables)

print(f"Functions/methods : {len(callables)}")
print(f"Raw call triples  : {len(call_triples)}\n")

# Deduplicate for display
seen: set[tuple[str, str]] = set()
print(f"{'CALLER':<40} → {'CALLEE'}")
print("─" * 70)
for caller_qn, _caller_fp, callee_name in call_triples:
    key = (caller_qn, callee_name)
    if key in seen:
        continue
    seen.add(key)
    print(f"{caller_qn:<40} → {callee_name}")

# ──────────────────────────────────────────────
# 2. Ingest and query resolved edges from Neo4j
# ──────────────────────────────────────────────
print("\nIngesting into Neo4j to resolve call edges…")
with get_graph_store() as graph:
    graph.ingest(
        repo_id  = REPO_ID,
        label    = loader.label(),
        entities = all_entities,
    )

    # Show resolved callees for each function that has any
    print("\nResolved call edges (from Neo4j):")
    print("─" * 70)
    found_any = False
    for fn in callables:
        fn_id   = f"{REPO_ID}:{fn.file_path}:{fn.qualified_name}"
        callees = graph.get_callees(fn_id)
        if callees:
            found_any = True
            names = [c.get("qualified_name", "?") for c in callees]
            print(f"  {fn.qualified_name}")
            for name in names:
                print(f"    → {name}")

    if not found_any:
        print("  No resolved edges in this folder (all callees are external).")

print("\nDone.")
