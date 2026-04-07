## Skill: Documentation generation

You are generating or improving documentation.

1. Use `summarize` for a plain-English overview of a file, class, or module.
2. Use `generate_docstring` to produce a Google-style docstring for a function
   or method.
3. Use `semantic_search` or `file_reader` to fetch the source if you need to
   inspect the code yourself before writing.
4. Return only the requested documentation — no surrounding commentary.

### Tool parameter reference
- `summarize` — parameters: `target` (file path or qualified name), `repo_id`.
- `generate_docstring` — parameters: `function_id` (qualified name), `repo_id`.
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.
