You are an expert software architect. Write a comprehensive architecture overview
for the repository '{repo_id}' in {lang_name}.

Style: {style_description}

File inventory ({file_count} files):
{file_list}

Graph analysis:
{graph_ctx}

Code samples:
{ctx}

Write a well-structured Markdown document with these sections:
- **Overview** — one-paragraph summary of what the project does and why it exists
- **Architecture** — high-level design, layers, and structural patterns
- **Key Components** — the most important modules/packages and their responsibilities
- **Data Flow** — how data enters, moves through, and exits the system
- **Entry Points** — public-facing interfaces (CLI commands, API routes, functions)
- **Dependencies** — notable external libraries and why they are used

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
