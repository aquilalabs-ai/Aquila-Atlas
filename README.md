# Aquila-Atlas

**The Atlas of your codebase**

Navigate, understand, and refactor legacy systems with natural language. Aquila-Atlas ingests your entire codebase, maps dependencies, and answers questions about your code — helping developers ship faster and onboard quicker.

## Problem

1. **AI tools don't understand full systems** — Current AI assistants see files in isolation, missing the big picture
2. **Legacy codebases are hard to navigate** — Understanding how systems connect takes weeks, not hours
3. **Slow developer onboarding** — New team members spend months becoming productive

## Solution

- **Full repo ingestion and understanding** — Ingest entire codebases and understand architectural patterns
- **Dependency graph mapping** — Visualize how components interact and impact each other
- **Natural language queries over code** — Ask questions like "Where is user authentication handled?" or "What breaks if I change this file?"

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                INTERFACE LAYER   ✅ REST API built           │
│              Chat UI  │  REST API  │  VS Code Extension     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     REASONING LAYER          ✅ built        │
│        LangGraph Agent  │  LangChain Tools  │  MCP Server   │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     KNOWLEDGE LAYER          ✅ built        │
│      Neo4j (graph)  │  Qdrant (vectors)  │  PostgreSQL   │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                     INGESTION LAYER          ✅ built        │
│       GitHub API  │  Python AST parser  │  Chunker          │
└─────────────────────────────────────────────────────────────┘
```

**Graph Queries**: All Cypher queries are executed via the Neo4j MCP server for security and consistency.

---

## Development Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Foundation | ✅ Done | Project scaffold, CI, Docker stack |
| Phase 1 — Ingestion Layer | ✅ Done | Source loaders, AST parser, token-aware chunker |
| Phase 2 — Knowledge Layer | ✅ Done | Neo4j graph + Qdrant hybrid search + KnowledgeService |
| Phase 3 — Reasoning Layer | ✅ Done | LangGraph agent, 4 LangChain tools + MCP tools, 4 specialised chains, CLI chat |
| Phase 4.1 — REST API | ✅ Done | 18-endpoint FastAPI backend, Swagger UI, SSE streaming |
| Phase 4.2 — Chat UI | ✅ Done | React + Vite, streaming chat, Monaco source viewer |
| Phase 5 — Documentation | Planned | Auto-doc generation, Markdown export |
| Phase 6 — VS Code Extension | Planned | IDE plugin |

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — package manager
- Docker + Docker Compose
- LLM accessible via OpenAI-compatible endpoint (default: [Ollama](https://ollama.com) local)

### Setup

```bash
# Install dependencies
uv sync --group dev

# Start infrastructure (Neo4j, Qdrant, PostgreSQL)
docker compose up -d

# Copy and configure environment
cp .env.example .env   # then edit .env
```

### Configuration (`.env`)

```env
# LLM — default: Ollama local (swap base_url + api_key for OpenAI, Anthropic, etc.)
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2

# Embeddings
EMBEDDINGS_BASE_URL=http://localhost:11434/v1
EMBEDDINGS_API_KEY=ollama
EMBEDDINGS_MODEL=nomic-embed-text

# Neo4j MCP server (for graph queries)
MCP_URL=http://localhost:8080/mcp

# LangSmith tracing (optional — leave blank to disable)
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=aquila-atlas
```

---

## Usage

### 1. Ingest a Repository

```bash
uv run python playground/phase2/04_full_knowledge_pipeline.py
```

Or programmatically:

```python
from aquila_atlas.ingestion import LocalFolderLoader, chunk_files, parse
from aquila_atlas.knowledge import get_knowledge_service

loader = LocalFolderLoader("aquila_atlas")
files  = list(loader.load())

entities = [e for f in files for e in parse(f)]
chunks   = list(chunk_files(files))

svc = get_knowledge_service()
svc.graph.ingest(repo_id="my-repo", label=loader.label(), entities=entities)
svc.ingest_chunks(chunks, repo_id="my-repo")
```

### 2. Chat with Your Codebase

```bash
# Interactive multi-turn chat (token streaming)
aquila chat --repo my-repo

# Non-streaming mode
aquila chat --repo my-repo --no-stream
```

```
Aquila chat — repo: my-repo  (type 'exit' or 'quit' to end, 'reset' to clear history)
────────────────────────────────────────────────────────────────────────

You: How does the hybrid search work?

Aquila: The hybrid search in `aquila_atlas/knowledge/vector.py` combines
dense vector similarity with a BM25 sparse index...
```

**Graph Queries**: For structural questions (e.g., "What calls this function?"), the agent uses MCP tools (`get-schema`, `read-cypher`) to query the Neo4j graph safely.

### 3. Semantic Search (CLI)

```bash
aquila search "how is token-aware chunking implemented" --repo my-repo
aquila search "parse imports" --repo my-repo --type function --lang Python --top-k 5
```

### 4. Programmatic Agent

```python
from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning import CodebaseAgent

svc   = get_knowledge_service()
agent = CodebaseAgent(service=svc, repo_id="my-repo")

# Blocking
print(agent.chat("Where is authentication handled?"))

# Streaming
for token in agent.stream("Explain the ingestion pipeline"):
    print(token, end="", flush=True)
```

### 5. Chat UI

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

1. Click **Connect a repository** in the sidebar
2. Choose a source — **Local folder** (absolute path), **GitHub URL**, or **Zip upload** (drag & drop)
3. Ingestion runs in the background; the repo list updates automatically when done
4. Chat with your codebase — responses stream token-by-token with live status labels
5. Click any `` `file.py:42` `` citation to open the source in the built-in Monaco viewer
6. Each repo has its own independent chat — switching repos preserves history
7. Toggle dark/light mode with the button at the bottom of the sidebar

> Requires the API server: `uv run aquila serve` (port 8000)

### 6. REST API

Start the server:

```bash
uv run aquila serve                # http://localhost:8000
uv run aquila serve --reload       # with hot-reload (dev mode)
```

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

# Ingest a zip archive
curl -X POST http://localhost:8000/repos/upload \
  -F "repo_id=myproject" \
  -F "file=@/path/to/archive.zip"

# Poll for completion
curl http://localhost:8000/repos/myproject/status

# Semantic search
curl "http://localhost:8000/repos/myproject/search?q=how+does+auth+work&top_k=5"

# Chat (non-streaming JSON)
curl -X POST http://localhost:8000/repos/myproject/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is authentication handled?", "stream": false}'

# Chat (SSE streaming)
curl -N -X POST http://localhost:8000/repos/myproject/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain the ingestion pipeline", "stream": true}'
```

With auth enabled (`API_KEY=my-secret` in `.env`):

```bash
curl http://localhost:8000/repos/myproject/search?q=auth \
  -H "X-API-Key: my-secret"
```

### 7. Specialised Chains

```python
from aquila_atlas.knowledge import get_knowledge_service
from aquila_atlas.reasoning.chains import (
    answer_code_question,
    summarize_architecture,
    suggest_refactor,
    generate_readme_section,
)

svc = get_knowledge_service()

# Code Q&A
print(answer_code_question("What does VectorStore.search return?", "my-repo", svc))

# Architecture overview
print(summarize_architecture("my-repo", svc, focus="ingestion pipeline"))

# Refactor suggestions
print(suggest_refactor("chunk_file", "my-repo", svc))

# Generate README section
print(generate_readme_section("Configuration", "my-repo", svc))
```

---

## Playground

Interactive scripts for exploring each layer:

```bash
# Ingestion
uv run python playground/phase1/04_full_pipeline.py

# Knowledge layer
uv run python playground/phase2/04_full_knowledge_pipeline.py

# Reasoning layer — tools, agent, chains
uv run python playground/phase3/01_tools.py
uv run python playground/phase3/02_agent_chat.py
uv run python playground/phase3/03_agent_stream.py
uv run python playground/phase3/04_chains.py

# REST API layer (Phase 4.1) — requires server running: uv run aquila serve
uv run python playground/phase4/01_health.py
uv run python playground/phase4/02_ingest_and_status.py
uv run python playground/phase4/03_search.py
uv run python playground/phase4/04_chat.py
uv run python playground/phase4/05_graph.py
```

---

## Running Tests

```bash
uv run pytest --cov
```

---

## Advanced Features (Roadmap)

- **Impact analysis** — Predict what breaks before refactoring
- **Test generation** — Auto-generate tests for legacy functions
- **Architecture visualization** — Diagram your system's structure
- **VS Code extension** — Inline chat, "Explain this function", "Find usages"

---