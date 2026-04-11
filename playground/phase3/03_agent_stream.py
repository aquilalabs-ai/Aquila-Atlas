"""
PLAYGROUND — Phase 3 / LangGraph Agent (token streaming)
=========================================================
Demonstrates the CodebaseAgent streaming tokens in real time.
Prints each token as it arrives so you can observe the LLM
generating the response progressively.

Prerequisites:
    docker compose up -d
    Data ingested (playground/phase2/04_full_knowledge_pipeline.py)
    LLM + streaming support available

Run:
    uv run python playground/phase3/03_agent_stream.py
"""

from __future__ import annotations

import sys
import time

from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning import CodebaseAgent

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
REPO_ID = "playground-full"

QUERIES = [
    "Explain how hybrid search works in the vector store.",
    "What graph relationships does Neo4j store between files and functions?",
]

# ──────────────────────────────────────────────
# Stream responses
# ──────────────────────────────────────────────
svc = get_knowledge_service()
agent = CodebaseAgent(service=svc, repo_id=REPO_ID)

for i, query in enumerate(QUERIES, 1):
    print(f"\n[Query {i}] {query}")
    print("\nAquila: ", end="", flush=True)

    start = time.perf_counter()
    token_count = 0

    for token in agent.stream(query):
        sys.stdout.write(token)
        sys.stdout.flush()
        token_count += 1

    elapsed = time.perf_counter() - start
    print(f"\n\n  ↳ {token_count} tokens in {elapsed:.2f}s")
    print("─" * 70)

print("\nDone.")
