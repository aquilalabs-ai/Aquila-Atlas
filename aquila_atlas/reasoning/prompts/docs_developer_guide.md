You are a senior software engineer. Write a comprehensive **Developer Guide** for the project '{repo_id}' in {lang_name}.

Style: {style_description}

File inventory ({file_count} files):
{file_list}

Graph analysis (architecture, entry points, dependencies):
{graph_ctx}

Code samples and context:
{ctx}

Write a well-structured Markdown document with these sections:
- **Overview** — what this project does and its architectural philosophy (one short paragraph)
- **Development Setup** — prerequisites, how to clone, install dependencies, configure `.env`, and start the dev environment
- **Project Structure** — directory layout with a brief description of each top-level package/module; use a `text` fenced block for the tree
- **Architecture** — how the main components fit together (data flow, key abstractions, design patterns used); include a Mermaid diagram if helpful
- **Extension Guide** — step-by-step instructions for the most likely extension points (e.g., adding a new language parser, a new tool, a new API endpoint, a new doc scope); be concrete and reference actual files
- **Testing** — how to run the test suite, how tests are organized, and how to add new tests
- **Code Conventions** — linting/formatting commands, naming conventions, type-checking requirements, and any project-specific rules
- **Key Design Decisions** — 3–5 non-obvious choices and the rationale behind them (e.g., why a particular library was chosen, why a certain pattern is enforced)

Write for a developer who wants to understand, extend, or contribute to the project. Include file paths and function names where relevant.

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
