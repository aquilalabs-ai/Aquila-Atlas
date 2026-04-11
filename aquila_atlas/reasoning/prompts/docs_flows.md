You are an expert software engineer. Document the execution flow starting from '{name}' in repository '{repo_id}' in {lang_name}.

Style: {style_description}

Entry point: `{name}` in `{file_path}`

Call chain ({call_count} steps):
{call_tree}

Code context:
{ctx}

Write a Markdown document tracing the full execution flow:
- **Entry Point** — inputs, preconditions, and who calls this function
- **Call Sequence** — the ordered list of functions invoked, with a brief note on each step
- **Data Transformations** — how data is shaped, validated, or enriched along the chain
- **Error Paths** — exceptions that can be raised and how they propagate
- **Outputs** — what the flow produces and where results end up
