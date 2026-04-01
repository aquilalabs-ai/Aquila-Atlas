# Aquila-Atlas

**The Atlas of your codebase**

Navigate, understand, and refactor legacy systems with natural language. Aquila-Atlas ingests your entire codebase, maps dependencies, and answers questions about your code—helping developers ship faster and onboard quicker.

## Problem

1. **AI tools don't understand full systems** — Current AI assistants see files in isolation, missing the big picture
2. **Legacy codebases are hard to navigate** — Understanding how systems connect takes weeks, not hours
3. **Slow developer onboarding** — New team members spend months becoming productive

## Solution

- **Full repo ingestion and understanding** — Ingest entire codebases and understand architectural patterns
- **Dependency graph mapping** — Visualize how components interact and impact each other
- **Natural language queries over code** — Ask questions like "Where is user authentication handled?" or "What breaks if I change this file?"

## MVP Features

- **GitHub integration** — Connect any GitHub repository instantly
- **Code embeddings + semantic search** — Find related code even when names don't match
- **Q&A chat over code** — Ask natural language questions about your codebase
- **Basic documentation generation** — Auto-generate READMEs and API docs

## Advanced Features (Roadmap)

- **Impact analysis** — Predict what breaks before refactoring
- **Refactoring suggestions** — AI-driven code modernization recommendations
- **Test generation** — Auto-generate tests for legacy functions
- **Architecture visualization** — Diagram your system's structure and dependencies

---

## Development Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Foundation | **Done** | Project scaffold, CI, Docker stack |
| Phase 1 — Ingestion Layer | **Done** | Source loaders, AST parser, chunker |
| Phase 2 — Knowledge Layer | **Done** | Neo4j graph + Qdrant vector store + hybrid search |
| Phase 3 — Reasoning Layer | Planned | LangGraph agent, Q&A chains |
| Phase 4 — Interface Layer | Planned | FastAPI backend + React chat UI |
| Phase 5 — Documentation | Planned | Auto-doc generation, Markdown export |
| Phase 6 — VS Code Extension | Planned | IDE plugin |

See [ROADMAP.md](ROADMAP.md) for full details.

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — package manager
- Docker + Docker Compose

### Setup

```bash
# Install dependencies
uv sync --group dev

# Start infrastructure (Neo4j, Qdrant, Valkey)
docker compose up -d
```

### Try the Ingestion Pipeline

```python
uv run python

from aquila_atlas.ingestion import LocalFolderLoader, chunk_files, chunk_file_summary, parse

# Load a local folder
loader = LocalFolderLoader(".")
files = list(loader.load())
print(loader.metadata())          # languages, label

# Parse a single file
entities = parse(files[0])
for e in entities:
    print(e.type, e.qualified_name, e.visibility)

# Get the summary chunk for a file
summary = chunk_file_summary(entities)
print(summary.content)

# Full pipeline — all chunks for all files
for chunk in chunk_files(files):
    print(chunk.entity.file_path, chunk.token_count, "tokens")
```

### Try the Knowledge Layer

Start infrastructure first:

```bash
docker compose up -d
```

Ingest a folder and search it:

```python
uv run python

from aquila_atlas.ingestion import LocalFolderLoader, chunk_files, parse
from aquila_atlas.knowledge import get_knowledge_service

loader = LocalFolderLoader("aquila_atlas")
files  = list(loader.load())

# Parse entities for the graph
entities = []
for f in files:
    entities.extend(parse(f))

# Chunk for vector embeddings
chunks = list(chunk_files(files))

svc = get_knowledge_service()

# Ingest into Neo4j + Qdrant
svc.graph.ingest(repo_id="my-repo", label=loader.label(), entities=entities)
svc.ingest_chunks(chunks, repo_id="my-repo")

# Hybrid semantic + keyword search
results = svc.search("how are imports extracted", repo_id="my-repo", top_k=5)
for r in results:
    print(f"{r.score:.4f}  {r.file_path}:{r.start_line}  {r.qualified_name}")

# Graph context — callers, callees, file, parent class
ctx = svc.get_context("my-repo:aquila_atlas/ingestion/parser.py:_extract_imports")
print(ctx)
```

Or use the CLI directly:

```bash
aquila search "how is token chunking implemented" --repo my-repo
aquila search "parse imports" --repo my-repo --type function --lang Python --top-k 5
```

### Run Tests

```bash
uv run pytest --cov
```
