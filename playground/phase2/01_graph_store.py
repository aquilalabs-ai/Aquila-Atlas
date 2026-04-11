"""
PLAYGROUND — Phase 2 / Graph Store (Neo4j)
===========================================
Demonstrates the full Neo4j pipeline:
  1. Connect and ensure schema constraints
  2. Parse a local folder and ingest into Neo4j
  3. Run traversal queries — callers, callees, imports, context

Prerequisites:
    docker compose up -d   (starts Neo4j on bolt://localhost:7687)

Run:
    uv run python playground/phase2/01_graph_store.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, parse
from aquila_atlas.knowledge import get_graph_store

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
TARGET = "aquila_atlas/ingestion"  # folder to ingest
REPO_ID = "playground-ingestion"

# ──────────────────────────────────────────────
# 1. Parse entities from folder
# ──────────────────────────────────────────────
loader = LocalFolderLoader(TARGET)
files = list(loader.load())

all_entities = []
for f in files:
    all_entities.extend(parse(f))

print(f"Parsed {len(all_entities)} entities from {len(files)} files\n")

by_type: dict[str, int] = {}
for e in all_entities:
    by_type[e.type] = by_type.get(e.type, 0) + 1
for t, n in sorted(by_type.items()):
    print(f"  {t:<12} {n}")

# ──────────────────────────────────────────────
# 2. Ingest into Neo4j
# ──────────────────────────────────────────────
print("\nConnecting to Neo4j and ingesting…")
with get_graph_store() as graph:
    graph.ingest(
        repo_id=REPO_ID,
        label=loader.label(),
        entities=all_entities,
        commit_sha=None,
    )
    print("Ingest complete.\n")

    # ──────────────────────────────────────────
    # 3. Traversal queries
    # ──────────────────────────────────────────

    # Pick the first function entity to demonstrate context lookup
    functions = [e for e in all_entities if e.type == "function"]
    if functions:
        sample = functions[0]
        fn_id = f"{REPO_ID}:{sample.file_path}:{sample.qualified_name}"

        print(f"Context for function: {sample.qualified_name}  ({sample.file_path})")
        ctx = graph.get_context(fn_id)
        print(f"  File       : {ctx['file']}")
        print(f"  Callers    : {len(ctx['callers'])}")  # type: ignore[arg-type]
        print(f"  Callees    : {len(ctx['callees'])}")  # type: ignore[arg-type]
        print(f"  Parent cls : {ctx['parent_class']}\n")

        print("Callees:")
        for callee in ctx["callees"]:  # type: ignore[union-attr]
            print(f"  → {callee.get('qualified_name', '?')}  ({callee.get('file_path', '?')})")

    # Import graph for the first file
    file_entities = [e for e in all_entities if e.type == "file"]
    if file_entities:
        sample_file = file_entities[0]
        file_id = f"{REPO_ID}:{sample_file.file_path}"

        print(f"\nImports from: {sample_file.file_path}")
        imports = graph.get_file_imports(file_id)
        if imports:
            for imp in imports:
                print(f"  → {imp.get('file_path', '?')}")
        else:
            print("  (none resolved in this folder)")

        print("\nImported by:")
        importers = graph.get_file_importers(file_id)
        if importers:
            for imp in importers:
                print(f"  ← {imp.get('file_path', '?')}")
        else:
            print("  (none in this folder)")

print("\nDone.")
