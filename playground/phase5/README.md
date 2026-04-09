# Playground — Phase 5: Documentation Generation

Developer sandbox for exploring the Aquila-Atlas documentation generation API.
These scripts exercise each part of the docs pipeline directly with `httpx`.

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
| `01_generate_and_poll.py` | Submit a doc job, poll progress, fetch content when done |
| `02_scopes.py` | Run all five scopes in sequence and compare file counts + duration |
| `03_skip_extensions.py` | Compare default vs explicit extension filter — which files get documented |
| `04_saved_docs.py` | List, load, and delete saved docs from the database; demonstrate cancel |
| `05_download_zip.py` | Download the ZIP archive, inspect its two-layer structure |

---

## How to Run

```bash
# from the repo root, with the server running in another terminal
uv run python playground/phase5/01_generate_and_poll.py
uv run python playground/phase5/02_scopes.py
uv run python playground/phase5/03_skip_extensions.py
uv run python playground/phase5/04_saved_docs.py
uv run python playground/phase5/05_download_zip.py
```

---

## Suggested Experiments

**Try a different scope** — open `01_generate_and_poll.py` and change:
```python
SCOPE = "architecture"   # single comprehensive overview
SCOPE = "per_module"     # one file per package (default)
SCOPE = "per_file"       # one file per source file
SCOPE = "subsystem"      # graph-clustered domain groups
SCOPE = "flows"          # call-chain entry-point traces
```

**Try a different language** — change `LANGUAGE` in `01_generate_and_poll.py`:
```python
LANGUAGE = "fr"   # French
LANGUAGE = "zh"   # Chinese
LANGUAGE = "de"   # German
```

**Try functional style** — change `STYLE`:
```python
STYLE = "functional"   # for PM / QA (behaviour, rules, configuration)
STYLE = "technical"    # for developers (signatures, types, integration)
```

**Inspect extension filtering** — run `03_skip_extensions.py` against a repo
that has media, data, or compiled files to see which files are skipped.

**Examine ZIP layout** — after generating, run `05_download_zip.py`. The archive
always has `index.html` at root and all content under `files/`. Open `index.html`
locally to browse the generated docs without a server.

**Cancel a slow job** — `04_saved_docs.py` submits a `per_file` job and
immediately cancels it, then polls to confirm the status transitions to `failed`.

**Point at your own repo**:
```python
REPO_ID = "my-project"
# (ingest it first via playground/phase4/02_ingest_and_status.py)
```
