"""
PLAYGROUND — Phase 1 / Full Pipeline
======================================
End-to-end run: source → RawFile → CodeEntity → CodeChunk.
Prints a summary table of every chunk produced from a folder.

Run:
    uv run python playground/phase1/04_full_pipeline.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader, chunk_files

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
TARGET = "aquila_atlas/ingestion"   # change to any folder
MAX_TOKENS = 512

# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────
loader = LocalFolderLoader(TARGET)
files = list(loader.load())

print(f"Source   : {loader.label()}")
print(f"Metadata : {loader.metadata()}")
print(f"Files    : {len(files)}\n")

all_chunks = list(chunk_files(files, max_tokens=MAX_TOKENS))

print(f"{'FILE':<45} {'TYPE':<10} {'NAME':<35} {'IDX':<6} {'TOKENS'}")
print("-" * 105)

for c in all_chunks:
    e = c.entity
    idx = f"{c.chunk_index + 1}/{c.chunk_total}"
    print(f"{e.file_path:<45} {e.type:<10} {e.name:<35} {idx:<6} {c.token_count}")

# ──────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("STATS")
print("=" * 60)

total_tokens = sum(c.token_count for c in all_chunks)
by_type: dict[str, int] = {}
for c in all_chunks:
    by_type[c.entity.type] = by_type.get(c.entity.type, 0) + 1

print(f"Total chunks : {len(all_chunks)}")
print(f"Total tokens : {total_tokens}")
print(f"Avg tokens   : {total_tokens // len(all_chunks) if all_chunks else 0}")
print()
for t, count in sorted(by_type.items()):
    print(f"  {t:<12} {count} chunks")
