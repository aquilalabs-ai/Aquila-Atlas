"""
PLAYGROUND — Phase 1 / Chunker
================================
Explore how CodeEntity objects get split into token-bounded CodeChunks.

Run:
    uv run python playground/phase1/03_chunker.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, parse
from aquila_atlas.ingestion.chunker import chunk_entity, chunk_file_summary

# ──────────────────────────────────────────────
# Config — tweak these to explore behaviour
# ──────────────────────────────────────────────
TARGET_FILE = "chunker.py"
MAX_TOKENS = 512      # lower this (e.g. 50) to force splits
OVERLAP_TOKENS = 50

# ──────────────────────────────────────────────
# Load + parse
# ──────────────────────────────────────────────
loader = LocalFolderLoader("aquila_atlas/ingestion")
files = {f.path: f for f in loader.load()}
raw = files[TARGET_FILE]
entities = parse(raw)

# ──────────────────────────────────────────────
# File-level summary chunk
# ──────────────────────────────────────────────
print("=" * 60)
print("FILE SUMMARY CHUNK")
print("=" * 60)

summary = chunk_file_summary(entities)
if summary:
    print(f"Token count : {summary.token_count}")
    print(f"\n{summary.content}")

# ──────────────────────────────────────────────
# Chunk each entity
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"ENTITY CHUNKS  (max_tokens={MAX_TOKENS}, overlap={OVERLAP_TOKENS})")
print("=" * 60)

print(f"\n{'TYPE':<10} {'QUALIFIED NAME':<40} {'CHUNKS':<8} {'TOKENS (each)'}")
print("-" * 75)

for entity in entities:
    chunks = chunk_entity(entity, max_tokens=MAX_TOKENS, overlap_tokens=OVERLAP_TOKENS)
    token_info = "  ".join(str(c.token_count) for c in chunks)
    print(f"{entity.type:<10} {entity.qualified_name:<40} {len(chunks):<8} {token_info}")

# ──────────────────────────────────────────────
# Drill into a specific entity's chunks
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("DRILL-DOWN: first function, all chunks")
print("=" * 60)

fn = next((e for e in entities if e.type == "function"), None)
if fn:
    chunks = chunk_entity(fn, max_tokens=MAX_TOKENS, overlap_tokens=OVERLAP_TOKENS)
    print(f"Entity  : {fn.qualified_name}  ({fn.end_line - fn.start_line + 1} lines)")
    print(f"Chunks  : {len(chunks)}\n")
    for c in chunks:
        print(f"--- chunk {c.chunk_index + 1}/{c.chunk_total}  ({c.token_count} tokens) ---")
        print(c.content)
        print()
