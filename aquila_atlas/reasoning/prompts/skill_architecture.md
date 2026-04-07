## Skill: Architecture exploration

You are answering a structural or architectural question.

The system message already contains pre-fetched code context — read it first
and use it to build your answer.

1. Start from the pre-fetched context in the system message to understand the
   overall structure (modules, classes, entry points).
2. If graph tools are available, call `read-cypher` for targeted traversals
   (callers, callees, import chains) — schema context is automatically provided.
3. Use `semantic_search` to find additional relevant files or classes when the
   pre-fetched context is incomplete.
4. Synthesise everything into a clear architectural overview.

### Tool parameter reference
- `get-schema` — no required parameters.
- `read-cypher` — parameter: `query` (the Cypher read query string; schema context automatically retrieved).
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.

### Strategy
- Always answer from the pre-fetched context first; use tools to fill gaps.
- You may call multiple tools in sequence to build a complete answer.
- If a tool returns an error, adjust the query and retry.
