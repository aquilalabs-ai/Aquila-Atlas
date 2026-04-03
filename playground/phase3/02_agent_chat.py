"""
PLAYGROUND — Phase 3 / LangGraph Agent (blocking chat)
=======================================================
Demonstrates the CodebaseAgent in blocking (non-streaming) mode.
Runs a fixed multi-turn conversation so you can see how context
accumulates across turns without interactive input.

Prerequisites:
    docker compose up -d
    Data ingested (playground/phase2/04_full_knowledge_pipeline.py)
    LLM available (default: Ollama llama3.2)

Run:
    uv run python playground/phase3/02_agent_chat.py
"""

from __future__ import annotations

from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning import CodebaseAgent

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
REPO_ID = "playground-full"

CONVERSATION = [
    "Give me a high-level overview of the ingestion layer.",
    "How does the chunker split large functions?",
    "Which file implements the vector store search?",
    "Show me the callers and callees for the search method.",
]

# ──────────────────────────────────────────────
# Run multi-turn conversation
# ──────────────────────────────────────────────
svc = get_knowledge_service()
agent = CodebaseAgent(service=svc, repo_id=REPO_ID)

print(f"Repository : {REPO_ID}")
print(f"Turns      : {len(CONVERSATION)}")
print("─" * 70)

for i, query in enumerate(CONVERSATION, 1):
    print(f"\n[Turn {i}] You: {query}")
    print("\nAquila:")
    answer = agent.chat(query)
    print(answer)
    print("─" * 70)

print(f"\nConversation history: {len(agent.history)} messages")
print("Done.")
