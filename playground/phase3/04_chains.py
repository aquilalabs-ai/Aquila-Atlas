"""
PLAYGROUND — Phase 3 / Specialised Chains
==========================================
Exercises each of the four focused chains independently:
  answer_code_question, summarize_architecture,
  suggest_refactor, generate_readme_section

These chains are lighter than the full agent — no routing, no
conversation memory — useful for batch or pipeline use cases.

Prerequisites:
    docker compose up -d
    Data ingested (playground/phase2/04_full_knowledge_pipeline.py)
    LLM available (default: Ollama llama3.2)

Run:
    uv run python playground/phase3/04_chains.py
"""

from __future__ import annotations

from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning.chains import (
    answer_code_question,
    generate_readme_section,
    suggest_refactor,
    summarize_architecture,
)

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
REPO_ID = "playground-full"

# ──────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────
svc = get_knowledge_service()

# ──────────────────────────────────────────────
# 1. Code Q&A chain
# ──────────────────────────────────────────────
print("=" * 70)
print("1. answer_code_question")
print("=" * 70)
answer = answer_code_question(
    query="What does the VectorStore.search method do and what does it return?",
    repo_id=REPO_ID,
    service=svc,
)
print(answer)
print()

# ──────────────────────────────────────────────
# 2. Architecture summary chain
# ──────────────────────────────────────────────
print("=" * 70)
print("2. summarize_architecture")
print("=" * 70)
summary = summarize_architecture(
    repo_id=REPO_ID,
    service=svc,
    focus="ingestion pipeline",  # set to None for the whole repo
)
print(summary)
print()

# ──────────────────────────────────────────────
# 3. Refactor suggestion chain
# ──────────────────────────────────────────────
print("=" * 70)
print("3. suggest_refactor")
print("=" * 70)
suggestions = suggest_refactor(
    target="ingestion/chunker.py",
    repo_id=REPO_ID,
    service=svc,
)
print(suggestions)
print()

# ──────────────────────────────────────────────
# 4. README doc generation chain
# ──────────────────────────────────────────────
print("=" * 70)
print("4. generate_readme_section")
print("=" * 70)
readme = generate_readme_section(
    section="Configuration",
    repo_id=REPO_ID,
    service=svc,
)
print(readme)
print()

print("Done.")
