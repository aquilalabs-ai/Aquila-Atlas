# Playground — Phase 1: Ingestion Layer

Developer sandbox for exploring the ingestion pipeline interactively.  
These scripts are **not tests** — they're tools for understanding and experimenting.

---

## Scripts

| Script | What it does |
|--------|-------------|
| `01_sources.py` | Load a folder / zip / GitHub repo → inspect `RawFile` list and metadata |
| `02_parser.py` | Parse a single file → inspect `CodeEntity` table, drill into one entity |
| `03_chunker.py` | Chunk entities → inspect token counts, force splits by lowering `MAX_TOKENS` |
| `04_full_pipeline.py` | End-to-end: folder → all chunks → summary stats |

---

## How to Run

```bash
# from the repo root
uv run python playground/phase1/01_sources.py
uv run python playground/phase1/02_parser.py
uv run python playground/phase1/03_chunker.py
uv run python playground/phase1/04_full_pipeline.py
```

---

## Suggested Experiments

**Force a chunk split** — open `03_chunker.py` and set:
```python
MAX_TOKENS = 50
```
You'll see large functions split into multiple overlapping chunks.

**Parse a different file** — change `TARGET_FILE` in `02_parser.py` to any `.py` path in the project.

**Try your own folder** — change `TARGET` in `04_full_pipeline.py` to any local path:
```python
TARGET = "/path/to/your/project"
```

**Try a GitHub repo** — uncomment the GitHub section in `01_sources.py`, set `REPO_URL`, and make sure `GITHUB_TOKEN` is in your environment.

**Try a zip** — uncomment the Zip section in `01_sources.py` and point `zip_path` at a `.zip` of any repo.
