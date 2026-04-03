"""
PLAYGROUND — Phase 3 / LangChain Tools
=======================================
Exercises each of the four reasoning-layer tools individually:
  SemanticSearchTool, FileReaderTool, SummaryTool, DocGenerationTool

Prerequisites:
    docker compose up -d
    Data already ingested (run playground/phase2/04_full_knowledge_pipeline.py first)
    LLM available (see .env — default: Ollama llama3.2)

Run:
    uv run python playground/phase3/01_tools.py
"""

from __future__ import annotations

from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning import get_tools

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
REPO_ID = "playground-full"
SEARCH_QUERY = "how is token-aware chunking implemented"
# Paths are stored relative to the TARGET folder used during ingestion.
# e.g. if TARGET="aquila_atlas", paths are stored as "ingestion/chunker.py"
FUNCTION_ID = f"{REPO_ID}:ingestion/chunker.py:chunk_files"
FILE_PATH = "ingestion/chunker.py"
SUMMARY_TARGET = "ingestion/chunker.py"
DOC_TARGET = "chunk_files"

# ──────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────
svc = get_knowledge_service()
tools = get_tools(svc)

tool_map = {t.name: t for t in tools}
print(f"Tools loaded: {[t.name for t in tools]}\n")

# ──────────────────────────────────────────────
# 0. Discovery — list available function IDs
#    (useful when you don't know the exact qualified_name)
# ──────────────────────────────────────────────
print("=" * 70)
print("0. graph discovery — functions in ingestion/chunker.py")
print("=" * 70)
with svc.graph._driver.session() as _session:
    _rows = _session.run(
        "MATCH (fn) WHERE fn.repo_id = $repo_id AND fn.file_path = $fp "
        "RETURN fn.id AS id, fn.qualified_name AS qn, labels(fn) AS lbl",
        repo_id=REPO_ID,
        fp="ingestion/chunker.py",
    )
    for _r in _rows:
        print(f"  {_r['lbl']}  {_r['qn']}  →  {_r['id']}")
print()

# ──────────────────────────────────────────────
# 1. SemanticSearchTool
# ──────────────────────────────────────────────
print("=" * 70)
print("1. semantic_search")
print("=" * 70)
result = tool_map["semantic_search"].invoke({"query": SEARCH_QUERY, "repo_id": REPO_ID, "top_k": 3})
print(result)
print()

# ──────────────────────────────────────────────
# 2. FileReaderTool
# ──────────────────────────────────────────────
print("=" * 70)
print("2. file_reader")
print("=" * 70)
result = tool_map["file_reader"].invoke({"file_path": FILE_PATH, "repo_id": REPO_ID})
# Print just the header + first chunk to keep output manageable
lines = result.split("\n")
print("\n".join(lines[:30]))
if len(lines) > 30:
    print(f"  … ({len(lines) - 30} more lines)")
print()

# ──────────────────────────────────────────────
# 3. SummaryTool
# ──────────────────────────────────────────────
print("=" * 70)
print("4. summarize")
print("=" * 70)
result = tool_map["summarize"].invoke({"target": SUMMARY_TARGET, "repo_id": REPO_ID})
print(result)
print()

# ──────────────────────────────────────────────
# 4. DocGenerationTool
# ──────────────────────────────────────────────
print("=" * 70)
print("5. generate_docstring")
print("=" * 70)
result = tool_map["generate_docstring"].invoke({"function_id": DOC_TARGET, "repo_id": REPO_ID})
print(result)
print()

print("Done.")
