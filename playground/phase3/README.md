# Playground — Phase 3: Reasoning Layer

Developer sandbox for exploring the LangGraph agent, LangChain tools, and specialised chains.
These scripts are **not tests** — they're tools for understanding and experimenting.

---

## Prerequisites

```bash
# Start all infrastructure (Neo4j · Qdrant · Valkey)
docker compose up -d

# Ingest data first (phase 2 pipeline must have run)
uv run python playground/phase2/04_full_knowledge_pipeline.py

# LLM (default: Ollama llama3.2)
ollama pull llama3.2
```

Or configure a different LLM provider in `.env`:
```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

Enable LangSmith tracing (optional):
```env
LANGSMITH_API_KEY=ls__...
LANGSMITH_PROJECT=aquila-atlas
```

---

## Scripts

| Script | What it does |
|--------|-------------|
| `01_tools.py` | Invoke each of the 4 LangChain tools individually — search, file reader, summarise, docstring generation |
| `02_agent_chat.py` | Run a fixed multi-turn conversation with the LangGraph agent in blocking mode — observe how context accumulates |
| `03_agent_stream.py` | Same agent but streaming — tokens printed in real time, with throughput stats |
| `04_chains.py` | Exercise each of the 4 specialised chains: Q&A, architecture summary, refactor suggestions, README section generation |

---

## How to Run

```bash
# from the repo root
uv run python playground/phase3/01_tools.py
uv run python playground/phase3/02_agent_chat.py
uv run python playground/phase3/03_agent_stream.py
uv run python playground/phase3/04_chains.py
```

---

## Suggested Experiments

**File paths are relative to the ingestion TARGET** — if you ingested `TARGET="aquila_atlas"`,
paths are stored as `"ingestion/chunker.py"`, not `"aquila_atlas/ingestion/chunker.py"`.
The semantic_search results always show the stored paths — use those as-is in other tools.

**Point at a different repo** — ingest any local folder and change `REPO_ID`:
```python
TARGET  = "/path/to/your/project"
REPO_ID = "my-project"
```

**Ask different questions** — edit `CONVERSATION` in `02_agent_chat.py`:
```python
CONVERSATION = [
    "Where is the database connection configured?",
    "What happens when a search returns no results?",
    "How would you test the ingestion pipeline?",
]
```

**Summarise a specific area** — edit the `focus` in `04_chains.py`:
```python
summarize_architecture(repo_id=REPO_ID, service=svc, focus="error handling")
summarize_architecture(repo_id=REPO_ID, service=svc, focus="authentication")
summarize_architecture(repo_id=REPO_ID, service=svc, focus=None)  # whole repo
```

**Generate different README sections**:
```python
generate_readme_section("Installation", repo_id=REPO_ID, service=svc)
generate_readme_section("API Reference", repo_id=REPO_ID, service=svc)
generate_readme_section("Contributing", repo_id=REPO_ID, service=svc)
```

**Try the interactive CLI**:
```bash
aquila chat --repo playground-full
aquila chat --repo playground-full --no-stream
```
