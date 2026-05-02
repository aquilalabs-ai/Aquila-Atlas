# Aquila-Atlas

**The Atlas of your codebase**

Navigate, understand, and refactor legacy systems with natural language. Aquila-Atlas ingests your entire codebase, maps dependencies, answers questions about your code, generates multi-scope documentation, creates test scaffolds across 13+ languages, and scans for security vulnerabilities — helping developers ship faster and onboard quicker.

## Problem

1. **AI tools don't understand full systems** — Current AI assistants see files in isolation, missing the big picture
2. **Legacy codebases are hard to navigate** — Understanding how systems connect takes weeks, not hours
3. **Slow developer onboarding** — New team members spend months becoming productive
4. **Test coverage is costly to bootstrap** — Writing tests for existing code is tedious, especially across polyglot repos
5. **Security debt is invisible** — Static scanners produce noise; developers need triaged, actionable findings

## Solution

- **Full repo ingestion** — Ingest entire codebases via local path, GitHub, GitLab, Gitea/Forgejo, Bitbucket, any git URL, or ZIP upload
- **Dependency graph mapping** — Visualise how files, classes, and functions connect and depend on each other
- **Natural language Q&A** — Ask "Where is user authentication handled?" or "What breaks if I change this file?"
- **AI-generated documentation** — Auto-generate per-file, per-module, architecture, subsystem, and execution-flow docs in 8 languages
- **Multi-language test generation** — Generate pytest, Jest, JUnit, Go test, RSpec and more scaffolds with syntax validation and fix loop
- **Security scanning** — semgrep + gitleaks + trivy + checkov static analysis followed by LLM triage: false-positive filtering, fix suggestions, OWASP Top 10 classification
- **Auth & licensing** — offline RSA instance license, per-seat key activation, LDAP/AD integration, session management, admin API

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERFACE LAYER                          │
│   React/Vite UI (Chat · Docs · Tests · Security)  │  FastAPI REST  │  CLI  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                       REASONING LAYER                           │
│  LangGraph Agent  │  19 LangChain Tools  │  MCP (Neo4j)        │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                       KNOWLEDGE LAYER                           │
│   Neo4j (graph)  │  Qdrant (vectors)  │  PostgreSQL + Valkey   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                       INGESTION LAYER                           │
│  Local · GitHub · GitLab · Gitea · Git clone · ZIP              │
│  tree-sitter (15 languages) · Python AST · COBOL parser         │
└─────────────────────────────────────────────────────────────────┘
```

The agent uses a 6-way router to classify every query before deciding how to answer:

```
router ──┬── "implementation" ──► vector retrieval ──► reasoning ──► [tool loop]
         ├── "structural"    ──► vector retrieval ──► reasoning ──► [tool loop]
         ├── "analysis"      ──► vector retrieval ──► reasoning ──► [tool loop]
         ├── "generation"    ──► vector retrieval ──► reasoning ──► [tool loop]
         ├── "diagram"       ──► vector retrieval ──► reasoning ──► [tool loop]
         └── "direct"        ────────────────────────► reasoning
```

Structural queries use MCP tools (`get-schema`, `read-cypher`) against Neo4j directly.

### Agent Tools (19)

| Tool | Purpose |
|---|---|
| `repo_overview` | One-shot overview: top entry points + call chains — use first for broad "how does this work" questions |
| `module_map` | Full module/package map with languages and per-file entity counts |
| `semantic_search` | Hybrid dense+sparse vector search over code chunks |
| `file_reader` | Fetch the full content of any ingested source file |
| `summarize` | Generate a plain-English summary of a file or class via LLM |
| `generate_docstring` | Generate a Google-style docstring for a function or method |
| `generate_mermaid` | Build a validated Mermaid diagram from live graph data |
| `validate_mermaid` | Check Mermaid syntax using the real Node.js Mermaid parser |
| `list_libs` | List all external libraries imported across the codebase |
| `find_callers` | Find every function that calls a given target via graph traversal |
| `list_entry_points` | List all public functions that are not called by any other code |
| `call_chain` | Trace the execution call tree from a function up to N hops |
| `git_log` | Recent commits and authors for a repo or specific file path |
| `git_status` | Uncommitted changes and working-tree status |
| `git_diff` | Diff between branches, commits, or working-tree state |
| `git_blame` | Line-by-line attribution for a file |
| `generate_tests` | On-demand test scaffold for a single file or `file::function` |
| `security_scan` | Targeted semgrep + LLM scan; returns top 10 findings with severity |
| `list_findings` | Query persisted security findings by severity and OWASP category |
| `get-schema` *(MCP)* | Retrieve the Neo4j graph schema |
| `read-cypher` *(MCP)* | Execute a read-only Cypher query against Neo4j |

---

## Development Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Foundation | ✅ Done | Project scaffold, CI, Docker stack |
| Phase 1 — Ingestion | ✅ Done | Source loaders (local/GitHub/GitLab/Gitea/git-clone/ZIP), 15-language parser (tree-sitter + Python AST + COBOL), token-aware chunker |
| Phase 2 — Knowledge | ✅ Done | Neo4j graph + Qdrant hybrid dense+sparse search + KnowledgeService facade |
| Phase 3 — Reasoning | ✅ Done | LangGraph agent, 6-way router, skill prompts, 19 LangChain tools, MCP tools, multi-provider LLM, CLI |
| Phase 4 — REST API + UI | ✅ Done | 37+ endpoint FastAPI backend, SSE streaming, Valkey job store, React/Vite Chat + Docs UI |
| Phase 5 — Documentation | ✅ Done | 5-scope AI doc generation, graph-enriched context, persistence, GitHub-style viewer |
| Phase 6 — Test Generation | ✅ Done | Multi-language test scaffolds (13 languages), 3 scopes, 7 API endpoints, CLI, chat tool |
| Phase 7 — Security Scanner | ✅ Done | semgrep + gitleaks + LLM triage, OWASP Top 10 classification, 5 API endpoints, CLI, 2 chat tools |
| Phase 8 — Test Delivery | ✅ Done | Annotated ZIP with per-file headers, README, CI snippet; Tests tab in UI |
| Phase 9 — Compilability | ✅ Done | Per-language syntax validation (9 languages), validate → fix loop (max 3 retries), generation quality guardrails |
| Phase 10 — Security UI | ✅ Done | SecurityPanel with findings explorer, severity filter, scan history; Security tab in main UI |
| Phase 11 — Auth & Licensing | ✅ Done | Offline RSA instance license, per-seat key activation, LDAP/AD auth, admin API, login UI |

---

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — package manager
- Docker + Docker Compose
- An LLM backend — Ollama (local default), or any of: OpenAI, Anthropic, Mistral, HuggingFace, or any OpenAI-compatible endpoint (Together, Groq, …)

### Setup

```bash
# Install dependencies
uv sync --group dev

# Start infrastructure (Neo4j, Qdrant, PostgreSQL, Valkey/Redis, MCP server)
docker compose up -d

# Copy and configure environment
cp .env.example .env   # then edit .env
```

### Configuration (`.env`)

```env
# LLM provider: openai | ollama | openai_compatible | anthropic | mistral | huggingface
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1   # used for openai/ollama/openai_compatible only
LLM_API_KEY=ollama
LLM_MODEL=llama3.2

# Embeddings — OpenAI-compatible endpoint (default: Ollama local)
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
# QDRANT_URL=https://...  # Qdrant Cloud (overrides host/port)
# QDRANT_API_KEY=         # Qdrant Cloud API key

# PostgreSQL — session, doc, test, and security scan persistence
POSTGRES_URL=postgresql://aquila:aquila@localhost:5432/aquila

# Valkey/Redis — background job store (leave blank to use in-process dict fallback)
VALKEY_URL=redis://localhost:6379/0

# Git hosting tokens — required for private repos; optional for rate-limit relief
GITHUB_TOKEN=
GITLAB_TOKEN=
GITEA_TOKEN=

# Neo4j MCP server
MCP_URL=http://localhost:8080/mcp

# API auth — leave blank for open/dev mode
API_KEY=

# User auth mode: disabled | key | ldap | both (default: disabled)
AUTH_MODE=disabled
# AQUILA_LICENSE_KEY=   # RS256 instance license JWT (required when AUTH_MODE != disabled)
# AQUILA_JWT_SECRET=    # HS256 secret for session tokens — set in production
# LDAP_URL=             # e.g. ldap://dc.company.com:389 (required for ldap/both modes)

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
- **GitHub** — `https://github.com/owner/repo` (set `GITHUB_TOKEN` for private repos)
- **GitLab** — `https://gitlab.com/group/repo` or self-hosted; set `GITLAB_TOKEN` for private repos
- **Gitea / Forgejo** — `https://gitea.example.com/owner/repo`; set `GITEA_TOKEN` for private repos
- **Any git URL** — HTTPS, SSH, or `file://` (Bitbucket, Azure DevOps, AWS CodeCommit, corporate SSH remotes)
- **ZIP archive** — via CLI flag or UI drag-and-drop

### 2. Chat with Your Codebase

```bash
uv run aquila chat --repo my-repo
uv run aquila chat --repo my-repo --no-mcp     # skip Neo4j MCP tools
uv run aquila chat --repo my-repo --no-stream  # non-streaming output
```

### 3. Semantic Search

```bash
uv run aquila search "how is token-aware chunking implemented" --repo my-repo
uv run aquila search "parse imports" --repo my-repo --top-k 5
```

### 4. Generate Test Scaffolds

```bash
# Generate tests for all Python files in per-file scope
uv run aquila tests --repo my-repo --scope per_file --lang python

# All supported languages, per-module scope
uv run aquila tests --repo my-repo --scope per_module

# Entry points only (most important public functions)
uv run aquila tests --repo my-repo --scope entry_points --output ./generated-tests/
```

Generated test files include:
- `[AQUILA] status: validated | syntax-only | unvalidated` header
- Per-file coverage and mock annotations
- `README.md` with install + run commands per framework
- GitHub Actions CI snippet for all detected languages

### 5. Security Scan

```bash
# Scan the ingested repo (semgrep + gitleaks + LLM triage)
uv run aquila security /path/to/repo --repo my-repo

# Skip LLM triage (faster, static only)
uv run aquila security /path/to/repo --repo my-repo --no-llm

# Custom semgrep ruleset
uv run aquila security /path/to/repo --repo my-repo --config p/owasp-top-ten
```

Static tools (all optional, gracefully degraded if not installed):
- **semgrep** — SAST rule-based analysis
- **gitleaks** — secrets and credential detection (always classified critical, CWE-798)
- **trivy** — SCA/CVE, container, Dockerfile, Terraform, K8s, Helm misconfigurations
- **checkov** — IaC specialist (Terraform, CloudFormation, K8s, GitHub Actions)

Output is grouped by severity:
- 🔴 **Critical** — exploitable issues (injection, secrets, hardcoded credentials)
- 🟠 **Major** — significant risks (broken access control, insecure deserialization)
- 🔵 **Minor** — informational findings (missing headers, low-risk patterns)

### 6. List Repos

```bash
uv run aquila repos
```

### 7. Programmatic Agent

```python
from aquila_atlas.knowledge.service import KnowledgeService
from aquila_atlas.reasoning.agent import CodebaseAgent

svc   = KnowledgeService(...)
agent = CodebaseAgent(service=svc, repo_id="my-repo")

# Blocking
print(agent.chat("Where is authentication handled?"))

# Async streaming with status events (used by the API)
async for event in agent.astream_with_status("What calls parse()?"):
    if "token" in event:
        print(event["token"], end="", flush=True)
    elif "status" in event:
        print(f"\n[{event['status']}]")
```

### 8. Web UI

Start the API server and frontend:

```bash
uv run aquila-serve          # http://localhost:8000

cd frontend
npm install && npm run dev   # http://localhost:5173
```

**Login** — When `AUTH_MODE` is set, users log in via seat key activation or LDAP/AD credentials before accessing any feature.

**Chat tab** — Multi-turn Q&A with streaming, suggestion chips, source citations, Monaco source viewer, and multi-session management.

**Docs tab** — Generate documentation with:
- 5 scopes: Architecture · Per module · Per file · Subsystems · Execution flows
- 2 styles: Technical (developers) · Functional (PM/QA)
- 8 output languages
- Filesystem tree browser, GitHub-style Markdown rendering, ZIP export, PostgreSQL persistence

**Tests tab** — Generate test scaffolds with:
- 3 scopes: Per file · Per module · Entry points
- Language filter chips (Python, TypeScript, Java, Go, Rust, …)
- Per-file status badges: `validated` · `syntax-only` · `unvalidated`
- Download annotated ZIP with README and GitHub Actions CI snippet
- Saved test sets with history browsing

**Security tab** — Scan and triage with:
- Target path input + semgrep config selector
- Findings grouped by severity: 🔴 Critical → 🟠 Major → 🔵 Minor
- Per-finding card: file path + line (→ Monaco), rule ID, OWASP category, LLM fix suggestion
- Filter by severity, OWASP category, or file path
- Scan history with timestamps and finding counts

### 9. REST API

Interactive Swagger UI at `http://localhost:8000/docs`.

```bash
# Ingest a local folder
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"source_type": "local", "path": "/home/user/myproject", "repo_id": "myproject"}'

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

# Generate test scaffolds
curl -X POST http://localhost:8000/repos/myproject/tests/generate \
  -H "Content-Type: application/json" \
  -d '{"scope": "per_file", "language_filter": ["python", "typescript"]}'

# Download tests as ZIP
curl -O http://localhost:8000/repos/myproject/tests/{job_id}/download-zip

# Run a security scan
curl -X POST http://localhost:8000/repos/myproject/security/scan \
  -H "Content-Type: application/json" \
  -d '{"source_type": "local", "path": "/home/user/myproject"}'

# Get scan findings
curl http://localhost:8000/repos/myproject/security/scans/{scan_id}

# Graph visualisation
curl http://localhost:8000/repos/myproject/graph
curl http://localhost:8000/repos/myproject/graph/stats
```

With auth enabled (`API_KEY=my-secret` in `.env`):

```bash
curl http://localhost:8000/repos/myproject/search?q=auth \
  -H "X-API-Key: my-secret"
```

---

## Language Support

### Parsing & Ingestion

| Language | Parser | Features |
|---|---|---|
| Python | `ast` (built-in) | Classes, functions, methods, imports, docstrings, decorators |
| JavaScript / TypeScript / JSX / TSX | Dedicated tree-sitter grammar | Arrow functions, JSDoc, interfaces, React components |
| Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin, Swift, Lua, Bash, Scala | `tree-sitter-language-pack` | Classes, functions, imports per language |
| COBOL | Custom regex parser | DIVISIONS, PARAGRAPHS, COPY/EXEC SQL INCLUDE, PERFORM/CALL edges |

Adding a new language is one line in `_LAZY_MODULES` (for tree-sitter-language-pack grammars) or a new parser file for languages needing special handling. See [ADD-LANGUAGE.md](ADD-LANGUAGE.md).

### Test Generation

| Language | Framework | Output pattern |
|---|---|---|
| Python | pytest | `tests/<module>/test_<name>.py` |
| TypeScript / JavaScript | Vitest | `src/__tests__/<name>.test.ts` |
| Java | JUnit 5 | `src/test/java/<pkg>/<Name>Test.java` |
| Go | `testing` stdlib | `<name>_test.go` (same package) |
| Rust | built-in `#[test]` | `tests/<name>.rs` |
| C# | xUnit | `<Name>Tests.cs` |
| Ruby | RSpec | `spec/<name>_spec.rb` |
| Kotlin | Kotest | `<Name>Test.kt` |
| PHP | PHPUnit | `tests/<Name>Test.php` |
| Swift | XCTest | `<Name>Tests.swift` |
| Scala | ScalaTest | `<Name>Spec.scala` |
| Bash | bats-core | `test_<name>.bats` |
| COBOL | — | stub with comments only |

### Syntax Validation (Compilability)

After generation, each file is validated before delivery:

| Language | Validator |
|---|---|
| Python | `ast.parse()` — stdlib, zero deps |
| TypeScript | `tsc --noEmit` with temp `tsconfig.json` |
| JavaScript | `node --check` |
| Java | `javac -proc:none` |
| Go | `gofmt -e` |
| Rust | `rustc --emit=metadata` |
| Ruby | `ruby -c` |
| PHP | `php -l` |
| Bash | `bash -n` |
| C# / Kotlin / Swift / Scala | skipped (no lightweight validator) |

Validation failures trigger an LLM fix loop (up to 3 retries). Final status per file: `validated` · `syntax-only` · `unvalidated`.

---

## Mermaid Diagram Validation

Diagram generation uses a **generate → validate → retry** loop (up to 5 attempts). Validation is performed by `mermaid_check.js` using the real `mermaid.parse()` engine — the same parser the browser uses. Falls back gracefully when Node.js is not available.

---

## Running Tests

```bash
uv run ruff check .                   # lint
uv run ruff format .                  # format
uv run python -m mypy aquila_atlas/   # type check
uv run python -m pytest               # all tests
```
