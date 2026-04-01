"""
PLAYGROUND — Phase 2 / Full Knowledge Pipeline
===============================================
End-to-end demonstration of the complete knowledge layer:
  folder → parse → chunk → Neo4j graph + Qdrant vectors → search

This is what the eventual `aquila ingest` + `aquila search` CLI will do.

Prerequisites:
    docker compose up -d
    Embeddings model available (see 02_vector_store.py for options)

Run:
    uv run python playground/phase2/04_full_knowledge_pipeline.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, chunk_files, parse
from aquila_atlas.knowledge import get_knowledge_service

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
TARGET   = "aquila_atlas"        # whole package
REPO_ID  = "playground-full"
QUERY    = "how is token-aware chunking implemented"
TOP_K    = 5

# ──────────────────────────────────────────────
# 1. Ingest: parse + chunk + store
# ──────────────────────────────────────────────
loader = LocalFolderLoader(TARGET)
files  = list(loader.load())

print(f"Source   : {loader.label()}")
print(f"Files    : {len(files)}")

# Parse entities for graph ingestion
all_entities = []
for f in files:
    all_entities.extend(parse(f))

# Produce chunks for vector ingestion
chunks = list(chunk_files(files))

by_type: dict[str, int] = {}
for e in all_entities:
    by_type[e.type] = by_type.get(e.type, 0) + 1

print(f"Entities : {len(all_entities)}  {dict(sorted(by_type.items()))}")
print(f"Chunks   : {len(chunks)}")
print()

svc = get_knowledge_service()

print("Step 1/2 — ingesting into Neo4j graph…")
svc.graph.ingest(
    repo_id   = REPO_ID,
    label     = loader.label(),
    entities  = all_entities,
    commit_sha= None,
)
print("  Graph ingest complete.")

print("Step 2/2 — embedding and upserting into Qdrant…")
svc.ingest_chunks(chunks, repo_id=REPO_ID)
print("  Vector upsert complete.\n")

# ──────────────────────────────────────────────
# 2. Search
# ──────────────────────────────────────────────
print(f'Search: "{QUERY}"')
print("─" * 70)

results = svc.search(QUERY, repo_id=REPO_ID, top_k=TOP_K)

if not results:
    print("No results found.")
else:
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r.score:.4f}  {r.file_path}:{r.start_line}-{r.end_line}  ({r.chunk_type})")
        print(f"     {r.qualified_name}  [{r.language}]")
        preview = r.content[:200].replace("\n", " ")
        print(f"     {preview}{'…' if len(r.content) > 200 else ''}\n")

# ──────────────────────────────────────────────
# 3. Graph context for the top result
# ──────────────────────────────────────────────
if results:
    top = results[0]
    fn_id = f"{REPO_ID}:{top.file_path}:{top.qualified_name}"
    print("─" * 70)
    print(f"Graph context for top result: {top.qualified_name}")
    ctx = svc.get_context(fn_id)
    print(f"  File       : {ctx['file']}")
    print(f"  Callers    : {len(ctx['callers'])}")    # type: ignore[arg-type]
    print(f"  Callees    : {len(ctx['callees'])}")    # type: ignore[arg-type]
    print(f"  Parent cls : {ctx['parent_class']}")

print("\nDone.")
