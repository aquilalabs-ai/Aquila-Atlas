# Aquila-Atlas

**The Atlas of your codebase**

Navigate, understand, and refactor legacy systems with natural language. Aquila-Atlas ingests your entire codebase, maps dependencies, answers questions about your code, and generates multi-scope documentation — helping developers ship faster and onboard quicker.

## Problem

1. **AI tools don't understand full systems** — Current AI assistants see files in isolation, missing the big picture
2. **Legacy codebases are hard to navigate** — Understanding how systems connect takes weeks, not hours
3. **Slow developer onboarding** — New team members spend months becoming productive

## Solution

- **Full repo ingestion** — Ingest entire codebases via local path, GitHub URL, or ZIP upload
- **Dependency graph mapping** — Visualise how files, classes, and functions connect and depend on each other
- **Natural language Q&A** — Ask "Where is user authentication handled?" or "What breaks if I change this file?"
- **AI-generated documentation** — Auto-generate per-file, per-module, architecture, subsystem, and execution-flow docs

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      INTERFACE LAYER                        │
│         React/Vite UI  │  FastAPI REST  │  CLI              │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     REASONING LAYER                         │
│     LangGraph Agent  │  LangChain Tools  │  MCP (Neo4j)     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     KNOWLEDGE LAYER                         │
│    Neo4j (graph)  │  Qdrant (vectors)  │  PostgreSQL        │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     INGESTION LAYER                         │
│  GitHub API  │  tree-sitter (15 languages)  │  Token chunker│
└─────────────────────────────────────────────────────────────┘
```

The agent uses a 4-way router to classify every query before deciding how to answer:

```
router ──┬── "implementation" ──► vector retrieval ──► reasoning ──► [tool loop]
         ├── "structural"  ─────────────────────────► reasoning ──► [tool loop]
         ├── "generation"  ─────────────────────────► reasoning ──► [tool loop]
         └── "direct"      ─────────────────────────► reasoning
```

Structural queries use MCP tools (`get-schema`, `read-cypher`) against Neo4j directly. All Cypher is executed via the Neo4j MCP server for safety and consistency.

---

## Development Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Foundation | ✅ Done | Project scaffold, CI, Docker stack |
| Phase 1 — Ingestion Layer | ✅ Done | Source loaders (local/GitHub/ZIP), tree-sitter parser (15 languages), token-aware chunker |
| Phase 2 — Knowledge Layer | ✅ Done | Neo4j graph + Qdrant hybrid dense+sparse search + KnowledgeService facade |
| Phase 3 — Reasoning Layer | ✅ Done | LangGraph agent, 4-way router, skill-based prompts, LangChain tools, MCP tools, CLI |
| Phase 4 — REST API + UI | ✅ Done | FastAPI backend (24+ endpoints), SSE streaming, React/Vite UI with Monaco viewer |
| Phase 5 — Documentation | ✅ Done | 5-scope AI doc generation, graph-enriched context, persistence, GitHub-style viewer |
| Phase 6 — VS Code Extension | Planned | IDE plugin |

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — package manager
- Docker + Docker Compose
- LLM accessible via an OpenAI-compatible endpoint (default: [Ollama](https://ollama.com) local)

### Setup

```bash
# Install dependencies
uv sync --group dev

# Start infrastructure (Neo4j, Qdrant, PostgreSQL, MCP server)
docker compose up -d

# Copy and configure environment
cp .env.example .env   # then edit .env
```

### Configuration (`.env`)

```env
# LLM — swap base_url + api_key for any OpenAI-compatible provider
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2

# Embeddings
EMBEDDINGS_BASE_URL=http://localhost:11434/v1
EMBEDDINGS_API_KEY=ollama
EMBEDDINGS_MODEL=nomic-embed-text

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# PostgreSQL — session + doc persistence
POSTGRES_URL=postgresql://aquila:aquila@localhost:5432/aquila

# Neo4j MCP server
MCP_URL=http://localhost:8080/mcp

# API auth — leave blank for open/dev mode
API_KEY=

# CORS — comma-separated origins (defaults cover Vite dev server)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# LangSmith tracing (optional)
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=aquila-atlas
```

---

## Usage

### 1. Ingest a Repository

```bash
uv run aquila ingest /path/to/repo --repo my-repo
```

Sources supported:
- **Local folder** — absolute path on disk
- **GitHub URL** — `https://github.com/owner/repo` (set `GITHUB_TOKEN` for private repos)
- **ZIP archive** — via CLI flag or UI drag-and-drop

### 2. Chat with Your Codebase

```bash
# Interactive multi-turn chat (streaming)
uv run aquila chat --repo my-repo

# Without MCP tools
uv run aquila chat --repo my-repo --no-mcp

# Non-streaming
uv run aquila chat --repo my-repo --no-stream
```

```
You: How does the hybrid search work?

Aquila: The hybrid search in `aquila_atlas/knowledge/vector.py` combines
dense vector similarity with a BM25 sparse index, merging results using
Reciprocal Rank Fusion (RRF)...
```

### 3. Semantic Search (CLI)

```bash
uv run aquila search "how is token-aware chunking implemented" --repo my-repo
uv run aquila search "parse imports" --repo my-repo --top-k 5
```

### 4. List Repos

```bash
uv run aquila repos
```

### 5. Programmatic Agent

```python
from aquila_atlas.knowledge.service import KnowledgeService
from aquila_atlas.reasoning.agent import CodebaseAgent

svc   = KnowledgeService(...)
agent = CodebaseAgent(service=svc, repo_id="my-repo")

# Blocking
print(agent.chat("Where is authentication handled?"))

# Streaming
for token in agent.stream("Explain the ingestion pipeline"):
    print(token, end="", flush=True)

# Async streaming with status events (used by the API)
async for event in agent.astream_with_status("What calls parse()?"):
    if "token" in event:
        print(event["token"], end="", flush=True)
    elif "status" in event:
        print(f"\n[{event['status']}]")
```

### 6. Web UI

Start the API server:

```bash
uv run aquila-serve          # http://localhost:8000
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

**Chat tab**:
1. Click **Connect a repository** in the sidebar
2. Choose a source — Local folder, GitHub URL, or ZIP upload
3. Ingestion runs in the background; the repo list updates when done
4. Chat with your codebase — responses stream token-by-token with live status labels
5. Click any `` `file.py:42` `` citation to open the source in the built-in Monaco viewer
6. Each repo keeps its own independent conversation history

**Docs tab**:
1. Select a scope — Architecture, Per module, Per file, Subsystems, or Execution flows
2. Choose a style (Technical / Functional) and language (8 supported)
3. Watch progress as each file is documented in real time
4. Browse the generated docs in a filesystem tree mirroring your repo structure
5. GitHub-style markdown rendering with syntax-highlighted code blocks
6. Copy individual files to clipboard or download the full set as a ZIP
7. Saved documentation persists in PostgreSQL and is accessible from the Saved tab

### 7. REST API

Interactive Swagger UI at `http://localhost:8000/docs`.

```bash
# Ingest a local folder
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"source_type": "local", "path": "/home/user/myproject", "repo_id": "myproject"}'

# Ingest a GitHub repository
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"source_type": "github", "path": "https://github.com/owner/repo", "repo_id": "myrepo"}'

# Ingest a ZIP archive
curl -X POST http://localhost:8000/repos/upload \
  -F "repo_id=myproject" \
  -F "file=@/path/to/archive.zip"

# List all repos
curl http://localhost:8000/repos

# Delete a repo (optionally cascade to sessions and docs)
curl -X DELETE "http://localhost:8000/repos/myproject?delete_sessions=true&delete_docs=true"

# Semantic search
curl "http://localhost:8000/repos/myproject/search?q=how+does+auth+work&top_k=5"

# Chat (SSE streaming)
curl -N -X POST http://localhost:8000/repos/myproject/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain the ingestion pipeline", "stream": true}'

# Generate documentation
curl -X POST http://localhost:8000/repos/myproject/docs/generate \
  -H "Content-Type: application/json" \
  -d '{"scope": "per_file", "style": "technical", "language": "en"}'

# Graph visualisation
curl http://localhost:8000/repos/myproject/graph
curl http://localhost:8000/repos/myproject/graph/stats
```

With auth enabled (`API_KEY=my-secret` in `.env`):

```bash
curl http://localhost:8000/repos/myproject/search?q=auth \
  -H "X-API-Key: my-secret"
```

### 8. Specialised Chains (batch use)

```python
from aquila_atlas.reasoning.chains import (
    answer_code_question,
    summarize_architecture,
    suggest_refactor,
    generate_readme_section,
)

print(answer_code_question("What does VectorStore.search return?", "my-repo", svc))
print(summarize_architecture("my-repo", svc, focus="ingestion pipeline"))
print(suggest_refactor("chunk_file", "my-repo", svc))
print(generate_readme_section("Configuration", "my-repo", svc))
```

---

## Running Tests

```bash
uv run ruff check .           # lint
uv run ruff format .          # format
uv run mypy aquila_atlas/     # type check
uv run pytest                 # all tests
```
