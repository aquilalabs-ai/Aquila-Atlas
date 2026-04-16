"""MermaidGeneratorTool and ValidateMermaidTool."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


_MERMAID_CYPHER: dict[str, str] = {
    "flowchart": """
        MATCH (src:File)-[:IMPORTS]->(tgt:File)
        WHERE src.repo_id = $repo_id
          AND ($scope = '' OR src.file_path CONTAINS $scope OR tgt.file_path CONTAINS $scope)
        RETURN src.file_path AS source, tgt.file_path AS target
        ORDER BY source
        LIMIT $limit
    """,
    "classDiagram": """
        MATCH (c:Class)
        WHERE c.repo_id = $repo_id
          AND ($scope = '' OR c.file_path CONTAINS $scope)
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Method)
        RETURN c.name AS cls, c.file_path AS file,
               collect(DISTINCT m.name) AS methods
        ORDER BY file, cls
        LIMIT $limit
    """,
    "sequenceDiagram": """
        MATCH (caller)-[:CALLS]->(callee)
        WHERE caller.repo_id = $repo_id
          AND ($scope = '' OR caller.file_path CONTAINS $scope)
        RETURN caller.name AS caller, caller.file_path AS caller_file,
               callee.name AS callee, callee.file_path AS callee_file
        ORDER BY caller
        LIMIT $limit
    """,
}

_MERMAID_GEN_SYSTEM = """\
You are a Mermaid diagram expert. Generate syntactically correct Mermaid diagrams
from structured codebase data.

STRICT RULES:
1. Start with exactly the correct diagram type line (e.g. "flowchart TD").
2. Node IDs must be SHORT ALPHANUMERIC identifiers — no slashes, dots, dashes, or spaces.
   Use the provided alias column (A, B, C, …) or invent short camelCase IDs.
   Display labels go inside square brackets: A["my/path/file.py"] --> B["other.py"]
3. Do NOT mix syntax from different diagram types.
4. Always wrap your diagram in ```mermaid fences — no prose before or after.
5. Keep it readable: max 35 nodes. Group or omit minor helpers if needed.
6. For flowchart: use 'flowchart TD' (or LR/RL). Edges use -->.
7. For classDiagram: list methods inside class block with '+'/'-' visibility.
8. For sequenceDiagram: declare participants, then messages using ->>/-->>.
"""


def _format_graph_data(diagram_type: str, rows: list[dict[str, Any]]) -> str:
    """Convert Cypher result rows into a prompt section with pre-assigned node aliases.

    For flowchart diagrams, each unique path is mapped to a short alphabetic alias
    (A, B, … Z, AA, AB, …) so the LLM does not need to invent valid Mermaid node IDs
    from raw file paths that contain slashes and dots.
    """
    if not rows:
        return "(no data found)"

    if diagram_type == "flowchart":
        # Assign short aliases to unique file paths
        alias_map: dict[str, str] = {}

        def _alias(path: str) -> str:
            if path not in alias_map:
                n = len(alias_map)
                # Base-26 label: A, B, …, Z, AA, AB, …
                label = ""
                n += 1
                while n:
                    n, rem = divmod(n - 1, 26)
                    label = chr(65 + rem) + label
                alias_map[path] = label
            return alias_map[path]

        edge_lines: list[str] = []
        for r in rows:
            src = str(r.get("source", "?"))
            tgt = str(r.get("target", "?"))
            edge_lines.append(f"  {_alias(src)} --> {_alias(tgt)}")

        alias_lines = [f'  {alias}["{path}"]' for path, alias in alias_map.items()]
        return (
            "Node aliases (use these exact IDs and labels in your diagram):\n"
            + "\n".join(alias_lines)
            + "\n\nEdges:\n"
            + "\n".join(edge_lines)
        )

    if diagram_type == "classDiagram":
        parts: list[str] = []
        for r in rows:
            methods = r.get("methods") or []
            mlist = ", ".join(str(m) for m in methods) if methods else "(none)"
            parts.append(
                f"  Class: {r.get('cls', '?')}  file: {r.get('file', '?')}  methods: {mlist}"
            )
        return "Classes and methods:\n" + "\n".join(parts)

    if diagram_type == "sequenceDiagram":
        lines = [
            f"  {r.get('caller', '?')} ({r.get('caller_file', '?')})  calls  "
            f"{r.get('callee', '?')} ({r.get('callee_file', '?')})"
            for r in rows
        ]
        return "Call relationships:\n" + "\n".join(lines)

    return "\n".join(str(r) for r in rows)


class MermaidInput(BaseModel):
    repo_id: str = Field(description="Repository ID")
    diagram_type: str = Field(
        description=(
            "Mermaid diagram type to generate. Choose based on the question:\n"
            "- 'flowchart'      → file-level import/dependency graph\n"
            "- 'classDiagram'   → class hierarchy and methods\n"
            "- 'sequenceDiagram'→ function call flows between components"
        ),
    )
    scope: str = Field(
        default="",
        description=(
            "Optional filter: a file path substring or module name to focus the diagram. "
            "Leave empty for the whole repository."
        ),
    )
    focus: str = Field(
        default="",
        description="Short description of what to emphasise, e.g. 'authentication flow'.",
    )


class MermaidGeneratorTool(BaseTool):
    """Generate a validated Mermaid diagram from live graph data.

    Queries Neo4j for the requested diagram type, prompts the LLM to render
    it as Mermaid syntax, then runs the built-in validator with up to two
    auto-fix retries.  Returns a fenced ```mermaid block ready for rendering.
    """

    name: str = "generate_mermaid"
    description: str = (
        "Generate a Mermaid diagram grounded in real codebase structure. "
        "Use for 'draw', 'visualise', 'show a diagram/graph/chart' requests. "
        "Produces flowchart (file deps), classDiagram (classes), or "
        "sequenceDiagram (call flows). Always returns a fenced ```mermaid block."
    )
    args_schema: type[BaseModel] = MermaidInput
    service: Any  # KnowledgeService
    llm: Any  # openai.OpenAI

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _MAX_ATTEMPTS: int = 5

    def _run(
        self,
        repo_id: str,
        diagram_type: str,
        scope: str = "",
        focus: str = "",
    ) -> str:
        from aquila_atlas.config import get_settings  # noqa: PLC0415
        from aquila_atlas.reasoning.mermaid import (  # noqa: PLC0415
            extract_mermaid_block,
            validate_with_node,
            wrap_in_fence,
        )

        logger.debug(
            "tool=generate_mermaid repo=%s type=%s scope=%r focus=%r",
            repo_id,
            diagram_type,
            scope,
            focus,
        )

        svc = cast("KnowledgeService", self.service)
        model = get_settings().llm_model

        # ── 1. Query graph data ───────────────────────────────────────────
        cypher = _MERMAID_CYPHER.get(diagram_type)
        if cypher is None:
            supported = ", ".join(f"'{k}'" for k in _MERMAID_CYPHER)
            return f"Unsupported diagram_type {diagram_type!r}. Supported: {supported}"

        try:
            rows = svc.graph.cypher_read(
                cypher,
                params={"repo_id": repo_id, "scope": scope, "limit": 40},
            )
        except Exception as exc:
            logger.warning("tool=generate_mermaid cypher failed: %s", exc)
            rows = []

        if not rows and not scope:
            return (
                f"No {diagram_type} data found for repo '{repo_id}'. "
                "The repository may not have been ingested yet."
            )

        # ── 2. Build initial LLM prompt with graph data ───────────────────
        graph_data = _format_graph_data(diagram_type, rows)
        focus_hint = f"\n\nEmphasise: {focus}" if focus else ""
        initial_prompt = (
            f"Generate a Mermaid {diagram_type} diagram for repository '{repo_id}'.\n\n"
            f"{graph_data}{focus_hint}\n\n"
            "Use the node aliases exactly as provided above. "
            "Wrap your response in ```mermaid fences — nothing else."
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _MERMAID_GEN_SYSTEM},
            {"role": "user", "content": initial_prompt},
        ]

        # ── 3. LLM generate → Node validate → feedback loop ──────────────
        # The LLM generates the diagram. If the Node.js mermaid.parse()
        # finds errors, they are added to the conversation and the LLM tries
        # again.  Repeat up to MAX_ATTEMPTS.
        diagram = ""
        last_errors: list[str] = []

        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            response = self.llm.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content or ""
            diagram = extract_mermaid_block(raw)

            errors = validate_with_node(diagram)
            if not errors:
                logger.info("tool=generate_mermaid valid after %d attempt(s)", attempt)
                return wrap_in_fence(diagram)

            last_errors = errors
            logger.info(
                "tool=generate_mermaid attempt %d/%d — %d error(s): %s",
                attempt,
                self._MAX_ATTEMPTS,
                len(errors),
                errors[:2],
            )

            if attempt < self._MAX_ATTEMPTS:
                error_list = "\n".join(f"- {e}" for e in errors)
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The diagram has syntax errors — fix them and return ONLY the "
                            "corrected diagram in ```mermaid fences.\n\n"
                            f"Errors:\n{error_list}"
                        ),
                    }
                )

        logger.warning(
            "tool=generate_mermaid all %d attempts exhausted — remaining errors: %s",
            self._MAX_ATTEMPTS,
            last_errors,
        )
        if not diagram:
            errors_str = "; ".join(last_errors) if last_errors else "unknown"
            return (
                f"Could not generate a valid {diagram_type} diagram after "
                f"{self._MAX_ATTEMPTS} attempts. Last errors: {errors_str}. "
                "Try a more specific scope or a different diagram type."
            )
        return wrap_in_fence(diagram)


class ValidateMermaidInput(BaseModel):
    diagram: str = Field(description="Mermaid diagram text to validate (fences optional)")
    repo_id: str = Field(description="Repository ID (context only)")


class ValidateMermaidTool(BaseTool):
    """Check a Mermaid diagram for syntax errors without calling the LLM.

    Use this to verify a manually written or previously generated diagram
    before presenting it to the user.  Returns 'valid' or a list of errors.
    """

    name: str = "validate_mermaid"
    description: str = (
        "Validate Mermaid diagram syntax. "
        "Call this after writing or editing a Mermaid diagram to catch errors "
        "before showing it to the user. "
        "Returns 'valid' on success or a list of error messages."
    )
    args_schema: type[BaseModel] = ValidateMermaidInput

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, diagram: str, repo_id: str) -> str:  # noqa: ARG002
        from aquila_atlas.reasoning.mermaid import validate_with_node  # noqa: PLC0415

        errors = validate_with_node(diagram)
        if not errors:
            return "valid"
        return "Syntax errors found:\n" + "\n".join(f"- {e}" for e in errors)
