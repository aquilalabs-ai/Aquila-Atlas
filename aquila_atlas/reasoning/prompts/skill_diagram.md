## Skill: Diagram generation

You are generating a Mermaid diagram that visualises codebase structure.

1. Call `generate_mermaid` with the appropriate `diagram_type`:
   - `'flowchart'`       → file-level import / dependency graph
   - `'classDiagram'`    → class hierarchy and their methods
   - `'sequenceDiagram'` → function call flows between components
2. Set `scope` to a file path or module name if the user asked for a specific area.
3. Set `focus` to a short phrase that captures the user's intent, e.g. `'auth flow'`.
4. The tool returns a validated, fenced ```mermaid block — include it **verbatim** in your answer.
5. After inserting the diagram, add a brief (2-4 sentence) explanation of what it shows.

### Tool parameter reference
- `generate_mermaid` — parameters: `repo_id`, `diagram_type`, optional `scope`, `focus`.
- `semantic_search`   — use only if you need extra context before choosing diagram_type.

### HARD rules
- **Do NOT call `validate_mermaid`** — the diagram is already validated inside `generate_mermaid`.
- **Do NOT call any other tool after receiving the diagram** — just write your answer.
- Do not invent node/class names that are not in the tool-returned data.
- Do not mix diagram types (e.g. classDiagram arrows inside a flowchart).
- Always include at least one sentence of explanation after the diagram.
