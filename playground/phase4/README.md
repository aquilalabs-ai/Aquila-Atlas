# Playground — Phase 4.1: REST API Backend

Developer sandbox for exploring the Aquila-Atlas FastAPI backend.
These scripts exercise each section of the API directly with `httpx` — no browser needed.

---

## Prerequisites

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Ingest data (phase 2 pipeline must have run at least once)
uv run python playground/phase2/04_full_knowledge_pipeline.py

# 3. Start the API server (keep this running in a separate terminal)
uv run aquila serve --reload
```

Swagger UI is available at `http://localhost:8000/docs` once the server is running.

### Optional: enable authentication

```env
# .env
API_KEY=my-secret
```

The playground scripts read `API_KEY` from the environment automatically.

---

## Scripts

| Script | What it does |
|--------|-------------|
| `01_health.py` | `GET /health` and `GET /health/ready` — verify the server is up and all backing services are reachable |
| `02_ingest_and_status.py` | `POST /repos` to trigger an ingestion job, then poll `GET /repos/{id}/status` until done |
| `03_search.py` | `GET /repos/{id}/search` — hybrid semantic search with various filters (chunk type, language, file) |
| `04_chat.py` | `POST /repos/{id}/chat` — non-streaming JSON and SSE streaming; multi-turn conversation using `session_id` |
| `05_graph.py` | `GET /repos/{id}/graph/stats`, `GET /repos/{id}/graph`, `POST /repos/{id}/graph/query` — inspect the Neo4j knowledge graph via REST |

---

## How to Run

```bash
# from the repo root, with the server running in another terminal
uv run python playground/phase4/01_health.py
uv run python playground/phase4/02_ingest_and_status.py
uv run python playground/phase4/03_search.py
uv run python playground/phase4/04_chat.py
uv run python playground/phase4/05_graph.py
```

---

## Suggested Experiments

**Point at a different repo** — change `REPO_ID` and `INGEST_PATH` in `02_ingest_and_status.py`:
```python
INGEST_PATH = "/absolute/path/to/your/project"
REPO_ID     = "my-project"
```

**Try different search filters** — edit `03_search.py`:
```python
QUERY      = "database connection pooling"
CHUNK_TYPE = "class"          # file | class | function | method
LANGUAGE   = "Python"
TOP_K      = 5
```

**Multi-turn chat** — the `04_chat.py` script demonstrates carrying a `session_id` across turns.
Edit `CONVERSATION` to ask your own questions:
```python
CONVERSATION = [
    "What is the overall architecture?",
    "How does the vector search work?",
    "Show me the hybrid RRF merge logic.",
]
```

**Custom Cypher** — edit `05_graph.py` to run your own read-only queries:
```python
CYPHER = """
MATCH (f:Function {repo_id: $repo_id})
WHERE f.name CONTAINS 'search'
RETURN f.name AS name, f.file_path AS file
ORDER BY name
"""
```
