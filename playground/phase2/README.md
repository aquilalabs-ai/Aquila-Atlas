# Playground — Phase 2: Knowledge Layer

Developer sandbox for exploring the Neo4j graph store and Qdrant vector store.  
These scripts are **not tests** — they're tools for understanding and experimenting.

---

## Prerequisites

```bash
# Start all infrastructure (Neo4j · Qdrant · Valkey)
docker compose up -d

# Embeddings (default: Ollama nomic-embed-text)
ollama pull nomic-embed-text
```

Or configure a different embeddings provider in `.env`:
```env
EMBEDDINGS_BASE_URL=https://api.openai.com/v1
EMBEDDINGS_API_KEY=sk-...
EMBEDDINGS_MODEL=text-embedding-3-large
```

---

## Scripts

| Script | What it does |
|--------|-------------|
| `01_graph_store.py` | Parse a folder → ingest into Neo4j → run traversal queries (callers, callees, imports, context) |
| `02_vector_store.py` | Chunk a folder → embed → upsert into Qdrant → hybrid search with and without filters |
| `03_call_graph.py` | Extract raw call triples via AST → ingest → inspect resolved call edges in Neo4j |
| `04_full_knowledge_pipeline.py` | End-to-end: folder → graph + vectors → search → graph context on top result |

---

## How to Run

```bash
# from the repo root
uv run python playground/phase2/01_graph_store.py
uv run python playground/phase2/02_vector_store.py
uv run python playground/phase2/03_call_graph.py
uv run python playground/phase2/04_full_knowledge_pipeline.py
```

---

## Suggested Experiments

**Point at a real project** — change `TARGET` in any script:
```python
TARGET  = "/path/to/your/project"
REPO_ID = "my-project"
```

**Try different search queries** — edit `QUERY` in `02_vector_store.py` or `04_full_knowledge_pipeline.py`:
```python
QUERY = "where is authentication handled"
QUERY = "database connection setup"
QUERY = "error handling patterns"
```

**Filter by chunk type** — find only functions or classes:
```python
results = store.search(QUERY, repo_id=REPO_ID, top_k=10, chunk_type="function")
results = store.search(QUERY, repo_id=REPO_ID, top_k=10, chunk_type="class")
```

**Inspect the import graph** — open `01_graph_store.py` and change which `file_id` you query:
```python
file_id = f"{REPO_ID}:aquila_atlas/ingestion/parser.py"
print(graph.get_file_imports(file_id))
print(graph.get_file_importers(file_id))
```

**Try the CLI** — after running the pipeline once:
```bash
aquila search "how is token chunking implemented" --repo playground-full
aquila search "parse imports" --repo playground-full --type function --lang Python
```
