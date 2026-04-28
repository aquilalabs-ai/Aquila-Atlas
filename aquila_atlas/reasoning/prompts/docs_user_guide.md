You are a technical writer. Write a comprehensive **User Guide** for the project '{repo_id}' in {lang_name}.

Style: {style_description}

File inventory ({file_count} files):
{file_list}

Graph analysis (entry points, public API):
{graph_ctx}

Code samples and context:
{ctx}

Write a well-structured Markdown document with these sections:
- **Overview** — what this project does and who it is for (one short paragraph)
- **Installation & Setup** — how to install dependencies and configure the project (environment variables, config files)
- **Quick Start** — the minimal steps to get something working, with a concrete example
- **Features & Commands** — all public-facing CLI commands, API endpoints, or UI features; for each, explain its purpose, inputs, and outputs
- **Configuration Reference** — all configurable options, their defaults, and their effect
- **Common Workflows** — 2–4 step-by-step recipes for the most frequent use cases (e.g., "ingest a codebase and search it", "run a chat session")
- **Troubleshooting** — the 3–5 most common errors or gotchas with their solutions

Write for an end user who wants to use the project, not build or extend it. Avoid internal implementation details.

## Diagram and code formatting rules — follow these exactly

**Mermaid diagrams:**
- Always wrap every Mermaid diagram in a fenced code block with the `mermaid` language tag:
  ` ```mermaid ` … ` ``` `
- NEVER use parentheses `()` inside node labels. Parentheses break Mermaid syntax.
  - Wrong: `A(MyClass)` or `B["foo()"]`
  - Right:  `A[MyClass]` or `B["foo"]`
- Use square brackets `[…]` for rectangular nodes, `{…}` for diamond/decision nodes, `((…))` for circles only when the label contains no parentheses itself.
- Keep node labels short — no function signatures, no type annotations.

**Tree / directory representations:**
- Always use a fenced code block (` ``` ` or ` ```text `) for tree and directory listings. Never render them as plain prose or bullet lists.

**Shell commands:**
- Always wrap shell commands in ` ```bash ` fenced blocks.
