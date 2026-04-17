"""
PLAYGROUND — Phase 3 / LangChain Tools
=======================================
Exercises each of the 16 reasoning-layer tools individually.

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
FILE_PATH = "ingestion/chunker.py"
SUMMARY_TARGET = "ingestion/chunker.py"
DOC_TARGET = "chunk_files"
CALLEE_TARGET = "chunk_entity"

# ──────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────
svc = get_knowledge_service()
tools = get_tools(svc)

tool_map = {t.name: t for t in tools}
print(f"Tools loaded ({len(tools)}): {sorted(tool_map)}\n")

# ──────────────────────────────────────────────
# 0. Discovery — list available function IDs
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
# 1. repo_overview — broad entry-point summary
# ──────────────────────────────────────────────
print("=" * 70)
print("1. repo_overview")
print("=" * 70)
result = tool_map["repo_overview"].invoke({"repo_id": REPO_ID})
lines = result.split("\n")
print("\n".join(lines[:30]))
if len(lines) > 30:
    print(f"  … ({len(lines) - 30} more lines)")
print()

# ──────────────────────────────────────────────
# 2. module_map — directory structure + entity counts
# ──────────────────────────────────────────────
print("=" * 70)
print("2. module_map")
print("=" * 70)
result = tool_map["module_map"].invoke({"repo_id": REPO_ID})
lines = result.split("\n")
print("\n".join(lines[:30]))
if len(lines) > 30:
    print(f"  … ({len(lines) - 30} more lines)")
print()

# ──────────────────────────────────────────────
# 3. semantic_search
# ──────────────────────────────────────────────
print("=" * 70)
print("3. semantic_search")
print("=" * 70)
result = tool_map["semantic_search"].invoke({"query": SEARCH_QUERY, "repo_id": REPO_ID, "top_k": 3})
print(result)
print()

# ──────────────────────────────────────────────
# 4. file_reader
# ──────────────────────────────────────────────
print("=" * 70)
print("4. file_reader")
print("=" * 70)
result = tool_map["file_reader"].invoke({"file_path": FILE_PATH, "repo_id": REPO_ID})
lines = result.split("\n")
print("\n".join(lines[:30]))
if len(lines) > 30:
    print(f"  … ({len(lines) - 30} more lines)")
print()

# ──────────────────────────────────────────────
# 5. summarize
# ──────────────────────────────────────────────
print("=" * 70)
print("5. summarize")
print("=" * 70)
result = tool_map["summarize"].invoke({"target": SUMMARY_TARGET, "repo_id": REPO_ID})
print(result)
print()

# ──────────────────────────────────────────────
# 6. generate_docstring
# ──────────────────────────────────────────────
print("=" * 70)
print("6. generate_docstring")
print("=" * 70)
result = tool_map["generate_docstring"].invoke({"function_id": DOC_TARGET, "repo_id": REPO_ID})
print(result)
print()

# ──────────────────────────────────────────────
# 7. find_callers
# ──────────────────────────────────────────────
print("=" * 70)
print("7. find_callers")
print("=" * 70)
result = tool_map["find_callers"].invoke({"target": CALLEE_TARGET, "repo_id": REPO_ID})
print(result)
print()

# ──────────────────────────────────────────────
# 8. list_entry_points
# ──────────────────────────────────────────────
print("=" * 70)
print("8. list_entry_points")
print("=" * 70)
result = tool_map["list_entry_points"].invoke({"repo_id": REPO_ID, "top_k": 10})
print(result)
print()

# ──────────────────────────────────────────────
# 9. call_chain — BFS from a known entry point
# ──────────────────────────────────────────────
print("=" * 70)
print("9. call_chain")
print("=" * 70)
result = tool_map["call_chain"].invoke({"start": DOC_TARGET, "repo_id": REPO_ID, "max_depth": 4})
print(result)
print()

# ──────────────────────────────────────────────
# 10. list_libs
# ──────────────────────────────────────────────
print("=" * 70)
print("10. list_libs")
print("=" * 70)
result = tool_map["list_libs"].invoke({"repo_id": REPO_ID})
print(result)
print()

# ──────────────────────────────────────────────
# 11. generate_mermaid
# ──────────────────────────────────────────────
print("=" * 70)
print("11. generate_mermaid")
print("=" * 70)
result = tool_map["generate_mermaid"].invoke(
    {
        "query": "Show the call graph for chunk_entity",
        "repo_id": REPO_ID,
        "diagram_type": "flowchart",
    }
)
lines = result.split("\n")
print("\n".join(lines[:20]))
if len(lines) > 20:
    print(f"  … ({len(lines) - 20} more lines)")
print()

# ──────────────────────────────────────────────
# 12. validate_mermaid
# ──────────────────────────────────────────────
print("=" * 70)
print("12. validate_mermaid")
print("=" * 70)
result = tool_map["validate_mermaid"].invoke({"diagram": "graph TD\n  A-->B\n  B-->C"})
print(result)
print()

# ──────────────────────────────────────────────
# 13–16. Git tools
# ──────────────────────────────────────────────
print("=" * 70)
print("13. git_log")
print("=" * 70)
result = tool_map["git_log"].invoke({"repo_id": REPO_ID, "max_entries": 5})
print(result)
print()

print("=" * 70)
print("14. git_status")
print("=" * 70)
result = tool_map["git_status"].invoke({"repo_id": REPO_ID})
print(result)
print()

print("=" * 70)
print("15. git_diff")
print("=" * 70)
result = tool_map["git_diff"].invoke({"repo_id": REPO_ID})
lines = result.split("\n")
print("\n".join(lines[:20]))
if len(lines) > 20:
    print(f"  … ({len(lines) - 20} more lines)")
print()

print("=" * 70)
print("16. git_blame")
print("=" * 70)
result = tool_map["git_blame"].invoke({"repo_id": REPO_ID, "file_path": FILE_PATH, "max_lines": 10})
print(result)
print()

print("Done.")
