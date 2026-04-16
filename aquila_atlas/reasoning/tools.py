"""LangChain tool wrappers for the Aquila-Atlas reasoning layer.

Each tool wraps a capability from the knowledge layer (vector search, graph
traversal, file reading) or calls the LLM directly (summarisation, doc gen).
Tools are injected with a :class:`~aquila_atlas.knowledge.service.KnowledgeService`
instance and — where LLM calls are needed — an :class:`openai.OpenAI` client.
"""

from __future__ import annotations

import logging
import re as _re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _llm_complete(llm: Any, model: str, system: str, user: str, max_tokens: int = 3500) -> str:
    """Run a single chat completion and return the response text.

    Returns an error string (not raises) if the model produces no content,
    so callers stay simple.
    """
    response = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    if not content:
        reason = response.choices[0].finish_reason
        return f"No response generated. (finish_reason={reason!r}, model={model!r})"
    return str(content)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class SemanticSearchInput(BaseModel):
    query: str = Field(description="Natural language search query about the codebase")
    repo_id: str = Field(description="Repository ID to search within")
    top_k: int = Field(default=5, description="Number of results to return (1-20)")
    chunk_type: str | None = Field(
        default=None,
        description="Optionally filter by chunk type: 'file', 'class', 'function', or 'method'",
    )


class FileReaderInput(BaseModel):
    file_path: str = Field(description="File path relative to the repository root")
    repo_id: str = Field(description="Repository ID")


class SummaryInput(BaseModel):
    target: str = Field(
        description=(
            "File path (e.g. 'aquila_atlas/config.py') or fully-qualified "
            "class/function name to summarise"
        ),
    )
    repo_id: str = Field(description="Repository ID")


class DocGenerationInput(BaseModel):
    function_id: str = Field(
        description=(
            "Fully-qualified function or method name, "
            "e.g. 'VectorStore.search' or 'chunker.chunk_file'"
        ),
    )
    repo_id: str = Field(description="Repository ID")


# ---------------------------------------------------------------------------
# SemanticSearchTool
# ---------------------------------------------------------------------------


class SemanticSearchTool(BaseTool):
    """Hybrid semantic + keyword search over ingested code chunks."""

    name: str = "semantic_search"
    description: str = (
        "Search for relevant code using natural language. "
        "Returns ranked code chunks with file locations and scores. "
        "Use this first when exploring an unfamiliar part of the codebase."
    )
    args_schema: type[BaseModel] = SemanticSearchInput
    service: Any  # KnowledgeService — Any to satisfy Pydantic field

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        query: str,
        repo_id: str,
        top_k: int = 5,
        chunk_type: str | None = None,
    ) -> str:
        logger.debug(
            "tool=semantic_search repo=%s top_k=%d chunk_type=%s query=%r",
            repo_id,
            top_k,
            chunk_type,
            query,
        )
        svc = cast("KnowledgeService", self.service)
        results = svc.search(query=query, repo_id=repo_id, top_k=top_k, chunk_type=chunk_type)
        if not results:
            return (
                "STOP — semantic_search returned no results. "
                "Do NOT call semantic_search again with a different query. "
                "Switch immediately to read-cypher to query the graph database, "
                "or answer directly from the pre-fetched context in the system message."
            )
        parts: list[str] = []
        for i, r in enumerate(results, 1):
            preview = r.content[:400] + ("..." if len(r.content) > 400 else "")
            parts.append(
                f"[{i}] {r.file_path}:{r.start_line}-{r.end_line} "
                f"({r.chunk_type}) score={r.score:.4f}\n"
                f"    {r.qualified_name} [{r.language}]\n"
                f"    {preview}"
            )
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# FileReaderTool
# ---------------------------------------------------------------------------


class FileReaderTool(BaseTool):
    """Fetch the full content of a file from the vector store."""

    name: str = "file_reader"
    description: str = (
        "Retrieve the complete content of a source file. Returns all code "
        "chunks sorted by line number. Use this when you need full file context "
        "rather than just matching snippets."
    )
    args_schema: type[BaseModel] = FileReaderInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _MAX_OUTPUT_CHARS: int = 6000

    def _run(self, file_path: str, repo_id: str) -> str:
        logger.debug("tool=file_reader repo=%s path=%r", repo_id, file_path)
        svc = cast("KnowledgeService", self.service)
        # Use the file path as the query so BM25 matches token overlap
        results = svc.search(query=file_path, repo_id=repo_id, top_k=20, file_path=file_path)
        if not results:
            return f"No content found for: {file_path}"

        # Deduplicate by (start_line, end_line) and sort
        seen: set[str] = set()
        chunks = []
        for r in sorted(results, key=lambda x: x.start_line):
            key = f"{r.start_line}:{r.end_line}"
            if key not in seen:
                seen.add(key)
                chunks.append(r)

        header = f"# {file_path}  ({len(chunks)} chunks)\n\n"
        sections = [
            f"# Lines {c.start_line}-{c.end_line} [{c.chunk_type}]\n{c.content}" for c in chunks
        ]
        body = "\n\n---\n\n".join(sections)
        result = header + body
        if len(result) > self._MAX_OUTPUT_CHARS:
            result = result[: self._MAX_OUTPUT_CHARS] + f"\n\n[truncated — {len(chunks)} chunks total, showing first {self._MAX_OUTPUT_CHARS} chars]"
        return result


# ---------------------------------------------------------------------------
# SummaryTool
# ---------------------------------------------------------------------------


class SummaryTool(BaseTool):
    """Summarise a file or class on demand using the configured LLM."""

    name: str = "summarize"
    description: str = (
        "Generate a plain-English summary of a file, class, or module. "
        "Use this to quickly understand what a component does without reading "
        "every line of code."
    )
    args_schema: type[BaseModel] = SummaryInput
    service: Any  # KnowledgeService
    llm: Any  # openai.OpenAI

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, target: str, repo_id: str) -> str:
        logger.debug("tool=summarize repo=%s target=%r", repo_id, target)
        from aquila_atlas.config import get_settings  # noqa: PLC0415

        svc = cast("KnowledgeService", self.service)
        is_file = "/" in target or target.endswith(".py")
        results = svc.search(
            query=f"summary of {target}",
            repo_id=repo_id,
            top_k=8,
            file_path=target if is_file else None,
        )
        if not results:
            return f"No code found for: {target}"

        code_context = "\n\n".join(
            f"### {r.qualified_name} ({r.chunk_type})\n{r.content}" for r in results
        )
        return _llm_complete(
            self.llm,
            model=get_settings().llm_model,
            system=(
                "You are an expert software engineer. "
                "Summarise the provided code concisely — "
                "what it does, its main responsibilities, and any notable patterns. "
                "Be specific and cite function/class names where relevant."
            ),
            user=f"Summarise: {target}\n\nCode:\n{code_context}",
        )


# ---------------------------------------------------------------------------
# DocGenerationTool
# ---------------------------------------------------------------------------


class DocGenerationTool(BaseTool):
    """Generate a Google-style docstring for a function or method."""

    name: str = "generate_docstring"
    description: str = (
        "Generate a detailed Google-style docstring for a function or method. "
        "Describes parameters, return value, and behaviour. "
        "Use this to document undocumented or poorly-documented code."
    )
    args_schema: type[BaseModel] = DocGenerationInput
    service: Any  # KnowledgeService
    llm: Any  # openai.OpenAI

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, function_id: str, repo_id: str) -> str:
        logger.debug("tool=generate_docstring repo=%s id=%r", repo_id, function_id)
        from aquila_atlas.config import get_settings  # noqa: PLC0415

        svc = cast("KnowledgeService", self.service)
        results = svc.search(query=function_id, repo_id=repo_id, top_k=3, chunk_type="function")
        if not results:
            results = svc.search(query=function_id, repo_id=repo_id, top_k=3, chunk_type="method")
        if not results:
            return f"Function not found: {function_id}"

        top = results[0]
        return _llm_complete(
            self.llm,
            model=get_settings().llm_model,
            system=(
                "You are an expert Python developer. "
                "Generate a concise, accurate Google-style docstring for the given function. "
                "Return only the docstring body — no triple quotes, no surrounding code."
            ),
            user=f"Generate a docstring for: {top.qualified_name}\n\nSource code:\n{top.content}",
        )


# ---------------------------------------------------------------------------
# MermaidGeneratorTool
# ---------------------------------------------------------------------------

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
1. Start with exactly the correct diagram type line.
2. Node/class/participant names must NOT contain spaces — use snake_case or camelCase.
3. Do NOT mix syntax from different diagram types.
4. Return ONLY the raw Mermaid diagram — no markdown fences, no explanation, no prose.
5. Keep it readable: max 35 nodes. Group or omit minor helpers if needed.
6. For flowchart: use 'flowchart TD' (or LR/RL). Edges use -->. Node IDs use short aliases.
7. For classDiagram: list methods inside class block with '+'/'-' visibility.
8. For sequenceDiagram: declare participants, then messages using ->>/-->>.
"""


def _format_graph_data(diagram_type: str, rows: list[dict[str, Any]]) -> str:
    """Convert Cypher result rows into a human-readable prompt section."""
    if not rows:
        return "(no data found)"
    if diagram_type == "flowchart":
        lines = [f"  {r.get('source', '?')}  -->  {r.get('target', '?')}" for r in rows]
        return "File import edges:\n" + "\n".join(lines)
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
            "Return ONLY the diagram wrapped in ```mermaid fences."
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
            "tool=generate_mermaid all %d attempts exhausted — returning last attempt. "
            "Remaining errors: %s",
            self._MAX_ATTEMPTS,
            last_errors,
        )
        return wrap_in_fence(diagram)


# ---------------------------------------------------------------------------
# ValidateMermaidTool
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ListLibsTool
# ---------------------------------------------------------------------------


class ListLibsInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")


class ListLibsTool(BaseTool):
    """List all external libraries and packages imported by the codebase.

    Scans graph IMPORTS edges and vector-stored import metadata to surface
    every third-party dependency referenced in the repo — useful for
    understanding the technology stack and dependency surface.
    """

    name: str = "list_libs"
    description: str = (
        "List all external libraries and packages imported across the codebase. "
        "Use this to understand the technology stack or when asked about dependencies, "
        "requirements, or what libraries the project uses."
    )
    args_schema: type[BaseModel] = ListLibsInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=list_libs repo=%s", repo_id)
        svc = cast("KnowledgeService", self.service)

        # Pull import info from graph (IMPORTS edges on File nodes store raw import strings)
        try:
            rows = svc.graph.cypher_read(
                """
                MATCH (f:File {repo_id: $repo_id})
                WHERE f.imports IS NOT NULL AND size(f.imports) > 0
                RETURN f.file_path AS file_path, f.imports AS imports, f.language AS language
                ORDER BY f.file_path
                """,
                params={"repo_id": repo_id},
            )
        except Exception as exc:
            logger.warning("tool=list_libs cypher failed: %s", exc)
            rows = []

        if not rows:
            # Fallback: search vector store for import statements
            results = svc.search(
                query="import require from library dependency",
                repo_id=repo_id,
                top_k=20,
                chunk_type="file",
            )
            if not results:
                return f"No import data found for repo '{repo_id}'."
            lines = [f"- {r.file_path}: {r.content[:200]}" for r in results]
            return "Imports found (from vector search):\n" + "\n".join(lines)

        # Aggregate imports across all files, classify external vs internal
        external: dict[str, list[str]] = {}
        for row in rows:
            fp = str(row.get("file_path", ""))
            imports = row.get("imports") or []
            lang = str(row.get("language", "unknown"))
            if isinstance(imports, str):
                imports = [imports]
            for imp in imports:
                imp = str(imp).strip()
                if not imp:
                    continue
                # Heuristic: internal imports contain the repo path separator or relative dot
                is_internal = imp.startswith(".") or "/" in imp or "\\" in imp
                if not is_internal:
                    external.setdefault(imp, []).append(f"{fp} [{lang}]")

        if not external:
            return (
                f"No external library imports detected for repo '{repo_id}'. "
                "All imports appear to be internal (relative) paths."
            )

        sorted_libs = sorted(external.items(), key=lambda x: (-len(x[1]), x[0]))
        parts = [f"External libraries used in '{repo_id}' ({len(sorted_libs)} unique):\n"]
        for lib, usages in sorted_libs[:60]:
            usage_count = len(usages)
            sample_files = ", ".join(usages[:3])
            suffix = f" (and {usage_count - 3} more)" if usage_count > 3 else ""
            parts.append(f"  • {lib} — used in {sample_files}{suffix}")
        if len(sorted_libs) > 60:
            parts.append(f"  … and {len(sorted_libs) - 60} more libraries")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# FindCallersTool
# ---------------------------------------------------------------------------


class FindCallersInput(BaseModel):
    target: str = Field(
        description=(
            "Name of the function, method, or class to find callers for. "
            "Use the qualified name (e.g. 'VectorStore.search') or just the function name."
        )
    )
    repo_id: str = Field(description="Repository ID")


class FindCallersTool(BaseTool):
    """Find all callers of a given function, method, or class via graph traversal."""

    name: str = "find_callers"
    description: str = (
        "Find everything that calls a specific function, method, or class. "
        "Use this to understand the call graph, trace usages, or assess the impact of changing a component. "
        "Returns callers with their file locations."
    )
    args_schema: type[BaseModel] = FindCallersInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, target: str, repo_id: str) -> str:
        logger.debug("tool=find_callers repo=%s target=%r", repo_id, target)
        svc = cast("KnowledgeService", self.service)

        try:
            rows = svc.graph.cypher_read(
                """
                MATCH (caller)-[:CALLS]->(callee)
                WHERE callee.repo_id = $repo_id
                  AND (callee.name = $target OR callee.qualified_name CONTAINS $target)
                RETURN caller.qualified_name AS caller_name,
                       caller.file_path     AS caller_file,
                       callee.qualified_name AS callee_name,
                       callee.file_path     AS callee_file,
                       labels(caller)[0]   AS caller_kind
                ORDER BY caller_file, caller_name
                LIMIT 50
                """,
                params={"repo_id": repo_id, "target": target},
            )
        except Exception as exc:
            logger.warning("tool=find_callers cypher failed: %s", exc)
            rows = []

        if not rows:
            # Fallback: semantic search for usages
            results = svc.search(
                query=f"usage call {target}",
                repo_id=repo_id,
                top_k=8,
            )
            if not results:
                return f"No callers found for '{target}' in repo '{repo_id}'."
            parts = [f"No direct graph edges found. Semantic matches for '{target}' usages:\n"]
            for r in results:
                parts.append(f"  • {r.file_path}:{r.start_line} — {r.qualified_name}")
            return "\n".join(parts)

        callee_name = str(rows[0].get("callee_name", target))
        callee_file = str(rows[0].get("callee_file", ""))
        parts = [
            f"Callers of `{callee_name}` (in `{callee_file}`): {len(rows)} found\n"
        ]
        for row in rows:
            kind = str(row.get("caller_kind", "?")).lower()
            parts.append(
                f"  • [{kind}] {row.get('caller_name', '?')} "
                f"in {row.get('caller_file', '?')}"
            )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# ListEntryPointsTool
# ---------------------------------------------------------------------------


class ListEntryPointsInput(BaseModel):
    repo_id: str = Field(description="Repository ID")


class ListEntryPointsTool(BaseTool):
    """List all public entry-point functions that have no incoming callers."""

    name: str = "list_entry_points"
    description: str = (
        "List all public functions and methods that are entry points — i.e. they are "
        "not called by any other code in the repository. These are the starting points "
        "of execution flows. Use this to understand how the application is invoked."
    )
    args_schema: type[BaseModel] = ListEntryPointsInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=list_entry_points repo=%s", repo_id)
        svc = cast("KnowledgeService", self.service)
        entry_points = svc.get_entry_points(repo_id)

        if not entry_points:
            return (
                f"No entry points found for repo '{repo_id}'. "
                "Either the repo has no public functions, or CALLS edges were not created "
                "(check that the language parser extracts call relationships)."
            )

        by_file: dict[str, list[dict[str, Any]]] = {}
        for ep in entry_points:
            fp = str(ep.get("file_path", "unknown"))
            by_file.setdefault(fp, []).append(ep)

        parts = [f"Entry points in '{repo_id}': {len(entry_points)} total\n"]
        for fp in sorted(by_file):
            parts.append(f"  {fp}:")
            for ep in by_file[fp]:
                kind = str(ep.get("kind", "function")).lower()
                score = ep.get("out_degree")
                score_hint = f" (calls {score} others)" if score else ""
                parts.append(f"    • [{kind}] {ep.get('name', '?')}{score_hint}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CallChainTool
# ---------------------------------------------------------------------------


class CallChainInput(BaseModel):
    start_function: str = Field(
        description=(
            "Qualified name or partial name of the starting function, "
            "e.g. 'VectorStore.search' or 'run_ingestion'."
        )
    )
    repo_id: str = Field(description="Repository ID")
    max_depth: int = Field(
        default=5,
        description="Maximum call-chain depth to trace (1-8). Default 5.",
    )


class CallChainTool(BaseTool):
    """Trace the call chain (call tree) starting from a given function.

    Performs BFS over CALLS edges in the graph up to *max_depth* hops,
    returning every reachable callee with its depth and file location.
    Useful for understanding execution flows, data pipelines, and side effects.
    """

    name: str = "call_chain"
    description: str = (
        "Trace the execution call chain starting from a function. "
        "Shows every function called directly or transitively from the starting point, "
        "up to the specified depth. Use for understanding flow, pipelines, and side effects."
    )
    args_schema: type[BaseModel] = CallChainInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, start_function: str, repo_id: str, max_depth: int = 5) -> str:
        logger.debug(
            "tool=call_chain repo=%s start=%r depth=%d", repo_id, start_function, max_depth
        )
        svc = cast("KnowledgeService", self.service)
        max_depth = max(1, min(max_depth, 8))

        # Resolve start_id — find a matching node first
        try:
            candidates = svc.graph.cypher_read(
                """
                MATCH (fn {repo_id: $repo_id})
                WHERE (fn:Function OR fn:Method)
                  AND (fn.name = $name OR fn.qualified_name CONTAINS $name)
                RETURN fn.id AS id, fn.qualified_name AS qn, fn.file_path AS fp
                LIMIT 5
                """,
                params={"repo_id": repo_id, "name": start_function},
            )
        except Exception as exc:
            logger.warning("tool=call_chain candidate lookup failed: %s", exc)
            candidates = []

        if not candidates:
            return (
                f"Function '{start_function}' not found in repo '{repo_id}'. "
                "Try the exact qualified name (e.g. 'ClassName.method_name')."
            )

        # Pick the best match (prefer exact name match)
        start = candidates[0]
        for c in candidates:
            if str(c.get("qn", "")).split("::")[-1] == start_function:
                start = c
                break

        start_id = str(start["id"])
        start_qn = str(start["qn"])
        start_fp = str(start["fp"])

        chain = svc.get_call_chain(repo_id, start_id, max_depth=max_depth)
        if not chain:
            return (
                f"`{start_qn}` ({start_fp}) has no outgoing calls recorded in the graph.\n"
                "Either the function makes no calls, or call relationships were not extracted "
                "for this language."
            )

        parts = [
            f"Call chain from `{start_qn}` (depth ≤{max_depth}):\n",
            f"  depth 0  →  {start_qn}  [{start_fp}]",
        ]
        for step in chain:
            indent = "  " + "  " * int(step.get("depth", 1))
            parts.append(
                f"{indent}depth {step['depth']}  →  {step['name']}  [{step.get('file_path', '?')}]"
            )
        parts.append(f"\nTotal reachable callees: {len(chain)}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Git tools — read-only git introspection for local and GitHub-hosted repos
# ---------------------------------------------------------------------------

_GIT_MAX_OUTPUT = 6000  # chars — truncate long output to keep context lean

# ── Source resolution ─────────────────────────────────────────────────────

_GH_REPO_RE = _re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:/tree/[^/].*)?/?$"
)


def _resolve_repo_source(
    svc: KnowledgeService, repo_id: str
) -> tuple[str, Any, str | None]:
    """Resolve *repo_id* to its ingested source.

    Returns one of:
    - ``("local", Path, None)``   — local directory that is a git repo
    - ``("github", url, None)``   — GitHub-hosted repo (URL string)
    - ``("error", None, message)``— unusable source with a human-readable reason
    """
    try:
        rows = cast("KnowledgeService", svc).graph.cypher_read(
            "MATCH (r:Repository {id: $repo_id}) RETURN r.label AS label",
            params={"repo_id": repo_id},
        )
    except Exception as exc:  # noqa: BLE001
        return "error", None, f"Could not look up repo '{repo_id}': {exc}"

    if not rows:
        return "error", None, (
            f"Repository '{repo_id}' not found. Has it been ingested yet? "
            "Run 'uv run aquila repos' to list available repositories."
        )

    label = str(rows[0].get("label") or "")
    if not label:
        return "error", None, f"Repository '{repo_id}' has no source path recorded."

    # GitHub URL
    if _GH_REPO_RE.match(label.rstrip("/")):
        return "github", label, None

    # Other remote URLs (GitLab, Bitbucket, raw git…) — no API support yet
    if label.startswith(("https://", "http://", "git@", "ssh://")):
        return "error", None, (
            f"Repository '{repo_id}' was ingested from a remote URL ({label}). "
            "Only GitHub and local git repositories are supported by the git tools."
        )

    # Local path
    path = Path(label)
    if not path.exists():
        return "error", None, (
            f"Source directory '{label}' no longer exists on disk. "
            "The repository may have been moved or deleted since ingestion."
        )

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return "error", None, "git is not installed or not found in PATH."
    except subprocess.TimeoutExpired:
        return "error", None, "git command timed out while detecting repository root."

    if result.returncode != 0:
        return "error", None, (
            f"'{label}' is not a git repository (no .git found). "
            "Git tools require the source folder to be initialised with git."
        )

    return "local", path, None


# ── Local git helpers ─────────────────────────────────────────────────────


def _run_git(path: Path, args: list[str], timeout: int = 30) -> tuple[str, str | None]:
    """Run a git command in *path*.  Returns ``(stdout, None)`` or ``('', error)``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return "", result.stderr.strip() or f"git exited with code {result.returncode}"
        out = result.stdout
        if len(out) > _GIT_MAX_OUTPUT:
            out = out[:_GIT_MAX_OUTPUT] + f"\n\n[truncated — output exceeds {_GIT_MAX_OUTPUT} chars]"
        return out, None
    except subprocess.TimeoutExpired:
        return "", "git command timed out."
    except FileNotFoundError:
        return "", "git is not installed or not found in PATH."


# ── GitHub REST API helpers ───────────────────────────────────────────────


def _gh_headers(token: str = "") -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _gh_get(path: str, token: str = "") -> tuple[Any, str | None]:
    """GET a GitHub API path.  Returns ``(data, None)`` or ``(None, error)``."""
    import httpx  # noqa: PLC0415

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"https://api.github.com{path}", headers=_gh_headers(token)
            )
            if resp.status_code == 404:
                hint = (
                    " If this is a private repository, set GITHUB_TOKEN in .env with"
                    " a token that has the 'repo' scope."
                    if not token
                    else " Verify the repository exists and your token has 'repo' scope access."
                )
                return None, f"GitHub: resource not found.{hint}"
            if resp.status_code == 401:
                return None, (
                    "GitHub: authentication failed — your GITHUB_TOKEN is invalid or expired."
                    " Generate a new token at https://github.com/settings/tokens"
                    " with the 'repo' scope."
                )
            if resp.status_code == 403:
                if "rate limit" in resp.text.lower():
                    return None, (
                        "GitHub: API rate limit exceeded."
                        " Set GITHUB_TOKEN in .env to get a higher rate limit (5000 req/h)."
                    )
                return None, (
                    "GitHub: access denied — your token lacks the required 'repo' scope"
                    " for this private repository."
                )
            resp.raise_for_status()
            return resp.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"GitHub API request failed: {exc}"


def _gh_owner_repo(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a GitHub URL, or return ``None``."""
    m = _GH_REPO_RE.match(url.rstrip("/"))
    if not m:
        return None
    return m.group("owner"), m.group("repo").removesuffix(".git")


def _gh_token() -> str:
    """Return the GitHub token from settings (empty string if not configured)."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    return get_settings().github_token


# ── GitLogTool ────────────────────────────────────────────────────────────


class GitLogInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    branch: str | None = Field(
        default=None,
        description=(
            "Optional: branch, tag, or commit SHA to read history from. "
            "Defaults to the current HEAD (local) or default branch (GitHub). "
            "Example: 'develop', 'feature/auth', 'v1.2.0'."
        ),
    )
    limit: int = Field(
        default=20,
        description="Maximum number of commits to return (1-100). Default 20.",
    )
    file_path: str | None = Field(
        default=None,
        description=(
            "Optional: restrict the log to commits that touched a specific file "
            "(relative path from the repository root, e.g. 'src/main.py')."
        ),
    )


class GitLogTool(BaseTool):
    """Show recent commit history for a local or GitHub-ingested repository."""

    name: str = "git_log"
    description: str = (
        "Show the recent commit history (git log) for the repository. "
        "Returns commit hash, author, date, and message for each commit. "
        "Optionally filter by branch/tag and by file path. "
        "Works for local git repos and GitHub-hosted repos."
    )
    args_schema: type[BaseModel] = GitLogInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        branch: str | None = None,
        limit: int = 20,
        file_path: str | None = None,
    ) -> str:
        logger.debug(
            "tool=git_log repo=%s branch=%r limit=%d file=%r", repo_id, branch, limit, file_path
        )
        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        limit = max(1, min(limit, 100))

        if kind == "local":
            args = [
                "log",
                f"-{limit}",
                "--pretty=format:%h  %ad  %an  %s",
                "--date=short",
                "--no-color",
            ]
            if branch:
                args.append(branch)
            if file_path:
                args += ["--follow", "--", file_path]
            out, err2 = _run_git(source, args)
            if err2:
                return f"git log failed: {err2}"
            if not out.strip():
                return "No commits found (the repository may have no commits yet)."
            header = f"git log for '{repo_id}'"
            if branch:
                header += f" [{branch}]"
            if file_path:
                header += f" — {file_path}"
            return f"{header}  (last {limit}):\n\n{out}"

        # GitHub
        assert isinstance(source, str)
        parsed = _gh_owner_repo(source)
        if not parsed:
            return f"Could not parse GitHub URL: {source}"
        owner, repo = parsed
        qs = f"?per_page={limit}"
        if branch:
            qs += f"&sha={branch}"
        if file_path:
            qs += f"&path={file_path}"
        data, err2 = _gh_get(f"/repos/{owner}/{repo}/commits{qs}", _gh_token())
        if err2:
            return f"git log failed: {err2}"
        if not isinstance(data, list) or not data:
            return "No commits found."
        lines: list[str] = []
        for c in data:
            sha = str(c.get("sha", ""))[:7]
            info = c.get("commit", {})
            msg = str(info.get("message", "")).splitlines()[0]
            author = info.get("author") or {}
            name = str(author.get("name", ""))
            date = str(author.get("date", ""))[:10]
            lines.append(f"{sha}  {date}  {name}  {msg}")
        header = f"git log for '{repo_id}' (GitHub)"
        if branch:
            header += f" [{branch}]"
        if file_path:
            header += f" — {file_path}"
        return f"{header}  (last {limit}):\n\n" + "\n".join(lines)


# ── GitStatusTool ─────────────────────────────────────────────────────────


class GitStatusInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")


class GitStatusTool(BaseTool):
    """Show working tree status (local) or latest branch/commit info (GitHub)."""

    name: str = "git_status"
    description: str = (
        "For local repos: show staged, unstaged, and untracked files (git status). "
        "For GitHub repos: show the default branch, latest commit, and open branch list. "
        "Useful for understanding the current state of the repository."
    )
    args_schema: type[BaseModel] = GitStatusInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=git_status repo=%s", repo_id)
        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "local":
            out, err2 = _run_git(source, ["status", "--short", "--branch"])
            if err2:
                return f"git status failed: {err2}"
            if not out.strip():
                return "Working tree is clean — no staged, unstaged, or untracked changes."
            return f"git status for '{repo_id}':\n\n{out}"

        # GitHub — no working tree; show repo summary instead
        assert isinstance(source, str)
        parsed = _gh_owner_repo(source)
        if not parsed:
            return f"Could not parse GitHub URL: {source}"
        owner, repo = parsed
        token = _gh_token()

        repo_data, err2 = _gh_get(f"/repos/{owner}/{repo}", token)
        if err2:
            return f"git status failed: {err2}"
        assert isinstance(repo_data, dict)
        default_branch = str(repo_data.get("default_branch", "main"))
        stars = repo_data.get("stargazers_count", 0)
        forks = repo_data.get("forks_count", 0)
        open_issues = repo_data.get("open_issues_count", 0)

        # Latest commit on default branch
        commit_data, _ = _gh_get(
            f"/repos/{owner}/{repo}/commits/{default_branch}", token
        )
        latest = ""
        if isinstance(commit_data, dict):
            sha = str(commit_data.get("sha", ""))[:7]
            info = commit_data.get("commit", {})
            msg = str(info.get("message", "")).splitlines()[0]
            author = (info.get("author") or {})
            name = str(author.get("name", ""))
            date = str(author.get("date", ""))[:10]
            latest = f"\nLatest commit on {default_branch}: {sha}  {date}  {name}  {msg}"

        # Branch list (up to 15)
        branches_data, _ = _gh_get(f"/repos/{owner}/{repo}/branches?per_page=15", token)
        branch_list = ""
        if isinstance(branches_data, list):
            names = [str(b.get("name", "")) for b in branches_data]
            branch_list = "\nBranches: " + ", ".join(names)

        return (
            f"git status for '{repo_id}' (GitHub — no working tree):\n"
            f"  Repository:    {owner}/{repo}\n"
            f"  Default branch: {default_branch}\n"
            f"  Stars: {stars}  Forks: {forks}  Open issues: {open_issues}"
            f"{latest}{branch_list}"
        )


# ── GitDiffTool ───────────────────────────────────────────────────────────


class GitDiffInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    ref1: str = Field(
        default="HEAD",
        description=(
            "Base git ref (commit SHA, branch, or tag). Defaults to 'HEAD'. "
            "For local repos, leave ref2 empty to diff the working tree against ref1."
        ),
    )
    ref2: str = Field(
        default="",
        description=(
            "Optional second ref to compare against ref1. "
            "For local repos: defaults to working tree. "
            "For GitHub repos: defaults to HEAD~1 when ref1 is HEAD, "
            "so the diff shows what the latest commit introduced."
        ),
    )
    file_path: str | None = Field(
        default=None,
        description="Optional: restrict the diff to a specific file (relative path).",
    )


class GitDiffTool(BaseTool):
    """Show a diff between git refs (local or GitHub)."""

    name: str = "git_diff"
    description: str = (
        "Show a git diff between two commits, branches, or tags. "
        "For local repos you can also compare against the working tree by leaving ref2 empty. "
        "For GitHub repos both refs are compared via the GitHub compare API. "
        "Works for local git repos and GitHub-hosted repos."
    )
    args_schema: type[BaseModel] = GitDiffInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        ref1: str = "HEAD",
        ref2: str = "",
        file_path: str | None = None,
    ) -> str:
        logger.debug(
            "tool=git_diff repo=%s ref1=%r ref2=%r file=%r", repo_id, ref1, ref2, file_path
        )
        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "local":
            args = ["diff", "--no-color"]
            if ref1:
                args.append(ref1)
            if ref2:
                args.append(ref2)
            if file_path:
                args += ["--", file_path]
            out, err2 = _run_git(source, args)
            if err2:
                return f"git diff failed: {err2}"
            if not out.strip():
                return "No differences found."
            label = f"{ref1}{'...' + ref2 if ref2 else ' (working tree)'}"
            header = f"git diff {label}"
            if file_path:
                header += f" -- {file_path}"
            return f"{header}:\n\n{out}"

        # GitHub — use compare API
        assert isinstance(source, str)
        parsed = _gh_owner_repo(source)
        if not parsed:
            return f"Could not parse GitHub URL: {source}"
        owner, repo = parsed
        token = _gh_token()

        # When ref2 is not supplied, compare ref1~1...ref1 (changes introduced by ref1)
        base = ref1 if ref1 else "HEAD"
        head = ref2 if ref2 else base
        if head == base:
            # Show what the commit at `base` introduced
            head = base
            base = f"{base}~1"

        data, err2 = _gh_get(f"/repos/{owner}/{repo}/compare/{base}...{head}", token)
        if err2:
            return f"git diff failed: {err2}"
        if not isinstance(data, dict):
            return "No diff data returned."

        files = data.get("files") or []
        if not files:
            return f"No differences between {base} and {head}."

        if file_path:
            files = [f for f in files if str(f.get("filename", "")) == file_path]
            if not files:
                return f"No diff for '{file_path}' between {base} and {head}."

        parts = [f"git diff {base}...{head} (GitHub — {len(files)} file(s) changed):\n"]
        total_chars = len(parts[0])
        for f in files:
            fname = f.get("filename", "?")
            status = f.get("status", "?")
            additions = f.get("additions", 0)
            deletions = f.get("deletions", 0)
            patch = str(f.get("patch", ""))
            entry = f"\n--- {fname}  [{status}  +{additions}/-{deletions}]\n{patch}"
            if total_chars + len(entry) > _GIT_MAX_OUTPUT:
                parts.append(f"\n[truncated — remaining files omitted]")
                break
            parts.append(entry)
            total_chars += len(entry)
        return "".join(parts)


# ── GitBlameTool ──────────────────────────────────────────────────────────


class GitBlameInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    file_path: str = Field(
        description="File to blame (relative path from the repository root, e.g. 'src/main.py')."
    )
    start_line: int | None = Field(
        default=None,
        description="Optional: first line of the range to blame (1-based).",
    )
    end_line: int | None = Field(
        default=None,
        description="Optional: last line of the range to blame (inclusive, 1-based).",
    )


class GitBlameTool(BaseTool):
    """Show per-line commit attribution (git blame) for a file."""

    name: str = "git_blame"
    description: str = (
        "Show who last modified each line of a file and in which commit (git blame). "
        "Optionally restrict to a line range. Useful for understanding the history of a "
        "specific piece of code or tracking down when a bug was introduced. "
        "Works for local git repos. GitHub repos are not supported (GitHub REST API "
        "does not expose blame; use git_log with a file_path filter instead)."
    )
    args_schema: type[BaseModel] = GitBlameInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        logger.debug(
            "tool=git_blame repo=%s file=%r lines=%s-%s",
            repo_id,
            file_path,
            start_line,
            end_line,
        )
        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "github":
            return (
                f"git blame is not available for GitHub-hosted repositories via the REST API. "
                f"Use git_log with file_path='{file_path}' to see which commits touched that file, "
                "then use git_diff to inspect a specific commit's changes."
            )

        args = ["blame", "--no-color", "-w"]
        if start_line is not None and end_line is not None:
            args += [f"-L{start_line},{end_line}"]
        elif start_line is not None:
            args += [f"-L{start_line},+50"]  # default 50 lines from start
        args.append(file_path)

        out, err2 = _run_git(source, args)
        if err2:
            return f"git blame failed: {err2}"
        if not out.strip():
            return f"No blame output for '{file_path}' — the file may not be tracked by git."

        header = f"git blame for '{file_path}'"
        if start_line:
            header += f" (lines {start_line}–{end_line or '…'})"
        return f"{header}:\n\n{out}"


# ---------------------------------------------------------------------------
# RepoOverviewTool
# ---------------------------------------------------------------------------

_PRIORITY_PREFIXES = ("main", "run", "handle", "start", "execute", "process", "create", "build")
_PRIORITY_FILE_STEMS = ("__main__", "cli", "main", "app", "server", "run")


def _score_entry_point(ep: dict[str, Any]) -> float:
    """Heuristic score for ranking entry points: out-degree + name/file hints."""
    score = float(ep.get("out_degree") or 0)
    name = str(ep.get("name", "")).lower()
    stem = str(ep.get("file_path", "")).split("/")[-1]
    stem = stem.rsplit(".", 1)[0].lower()
    if any(p in name for p in _PRIORITY_PREFIXES):
        score += 5
    if any(p in stem for p in _PRIORITY_FILE_STEMS):
        score += 3
    return score


class RepoOverviewInput(BaseModel):
    repo_id: str = Field(description="Repository ID to overview")
    max_entry_points: int = Field(
        default=3,
        description="Number of top entry points to expand with call chains (1-5).",
    )


class RepoOverviewTool(BaseTool):
    """One-shot codebase overview: top entry points with their call chains.

    Replaces the common ``list_entry_points`` + N × ``call_chain`` pattern by
    doing all the graph work internally and returning a single formatted digest.
    """

    name: str = "repo_overview"
    description: str = (
        "Return a complete codebase overview in ONE call: top entry points and their "
        "call chains (up to depth 3). "
        "Use this FIRST for questions about entry points, main execution flows, or "
        "'how does this codebase work'. "
        "Replaces list_entry_points + call_chain — do NOT call those separately afterwards."
    )
    args_schema: type[BaseModel] = RepoOverviewInput
    service: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str, max_entry_points: int = 3) -> str:
        logger.debug("tool=repo_overview repo=%s max_eps=%d", repo_id, max_entry_points)
        svc = cast("KnowledgeService", self.service)
        max_entry_points = max(1, min(max_entry_points, 5))

        # ── 1. All entry points (ranked by graph, re-scored here) ────────
        all_eps = svc.get_entry_points(repo_id)
        if not all_eps:
            return (
                f"No entry points found for repo '{repo_id}'. "
                "CALLS edges may not be available for this language — "
                "try semantic_search for 'main function' or 'entry point' instead."
            )
        top_eps = sorted(all_eps, key=_score_entry_point, reverse=True)[:max_entry_points]

        # ── 2. Resolve IDs + call chains for the top entry points ────────
        ep_chains: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for ep in top_eps:
            ep_name = str(ep.get("name", ""))
            try:
                rows = svc.graph.cypher_read(
                    """
                    MATCH (fn {repo_id: $repo_id})
                    WHERE (fn:Function OR fn:Method)
                      AND (fn.qualified_name = $name OR fn.name = $name)
                    RETURN fn.id AS id
                    LIMIT 1
                    """,
                    params={"repo_id": repo_id, "name": ep_name},
                )
                chain = svc.get_call_chain(repo_id, str(rows[0]["id"]), max_depth=3) if rows else []
            except Exception as exc:  # noqa: BLE001
                logger.warning("tool=repo_overview chain lookup failed for %r: %s", ep_name, exc)
                chain = []
            ep_chains.append((ep, chain))

        # ── 3. Format ─────────────────────────────────────────────────────
        parts: list[str] = [f"# Entry-point overview for '{repo_id}'\n"]
        parts.append(
            f"Total entry points found: {len(all_eps)} "
            f"(showing top {len(ep_chains)} by significance)\n"
        )

        for ep, chain in ep_chains:
            out_deg = ep.get("out_degree", 0)
            parts.append(
                f"## {ep.get('name', '?')}"
                f"  [{str(ep.get('kind', '?')).lower()}]"
                f"  {ep.get('file_path', '?')}"
                f"  (calls {out_deg} others)"
            )
            if chain:
                by_depth: dict[int, list[str]] = {}
                for step in chain:
                    d = int(step.get("depth", 1))
                    by_depth.setdefault(d, []).append(str(step.get("name", "?")))
                for depth in sorted(by_depth):
                    calls = ", ".join(by_depth[depth][:6])
                    if len(by_depth[depth]) > 6:
                        calls += f" (+{len(by_depth[depth]) - 6} more)"
                    parts.append(f"{'  ' * depth}  depth {depth}: {calls}")
            else:
                parts.append("  (no further calls recorded in graph)")
            parts.append("")

        if len(all_eps) > max_entry_points:
            parts.append(
                f"({len(all_eps) - max_entry_points} more entry points omitted — "
                "call list_entry_points for the full list)"
            )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# ModuleMapTool
# ---------------------------------------------------------------------------


class ModuleMapInput(BaseModel):
    repo_id: str = Field(description="Repository ID")


class ModuleMapTool(BaseTool):
    """Return the full module/package map of the repository.

    Groups all ingested files by their top-level directory and annotates each
    file with its class/function/method counts.  Reads entirely from the graph —
    no semantic search needed.
    """

    name: str = "module_map"
    description: str = (
        "Return a complete map of all modules and packages: directory structure, "
        "file list, languages, and per-file class/function/method counts. "
        "Use for questions about 'what modules/packages exist', 'describe the folder structure', "
        "'what files are there', or 'what languages are used'. "
        "Reads directly from the graph — no semantic search needed."
    )
    args_schema: type[BaseModel] = ModuleMapInput
    service: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _MAX_FILES: int = 200

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=module_map repo=%s", repo_id)
        svc = cast("KnowledgeService", self.service)

        # ── 1. All files ──────────────────────────────────────────────────
        try:
            file_rows = svc.graph.cypher_read(
                """
                MATCH (f:File {repo_id: $repo_id})
                RETURN f.file_path AS path, f.language AS lang
                ORDER BY f.file_path
                """,
                params={"repo_id": repo_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool=module_map file query failed: %s", exc)
            return f"Could not retrieve module map for '{repo_id}': {exc}"

        if not file_rows:
            return f"No files found for repo '{repo_id}'."

        # ── 2. Entity counts per file ─────────────────────────────────────
        try:
            entity_rows = svc.graph.cypher_read(
                """
                MATCH (n {repo_id: $repo_id})
                WHERE n:Function OR n:Method OR n:Class
                WITH n.file_path AS path,
                     CASE WHEN n:Class THEN 'class'
                          WHEN n:Method THEN 'method'
                          ELSE 'function' END AS kind
                RETURN path, kind, count(*) AS cnt
                """,
                params={"repo_id": repo_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool=module_map entity query failed: %s", exc)
            entity_rows = []

        entity_counts: dict[str, dict[str, int]] = {}
        for row in entity_rows:
            fp = str(row.get("path", ""))
            kind = str(row.get("kind", ""))
            entity_counts.setdefault(fp, {})[kind] = (
                entity_counts.get(fp, {}).get(kind, 0) + int(row.get("cnt", 0))
            )

        # ── 3. Group by top-level directory ───────────────────────────────
        dirs: dict[str, list[dict[str, Any]]] = {}
        for row in file_rows:
            fp = str(row.get("path", ""))
            lang = str(row.get("lang") or "?")
            parts_split = fp.replace("\\", "/").split("/")
            top_dir = parts_split[0] if len(parts_split) > 1 else "(root)"
            dirs.setdefault(top_dir, []).append({"path": fp, "lang": lang})

        # ── 4. Format ─────────────────────────────────────────────────────
        lines: list[str] = [f"# Module map for '{repo_id}'\n"]
        lines.append(f"Total files indexed: {len(file_rows)}\n")

        for top_dir in sorted(dirs):
            files = dirs[top_dir]
            lang_counts: dict[str, int] = {}
            for f in files:
                lang_counts[f["lang"]] = lang_counts.get(f["lang"], 0) + 1
            lang_str = ", ".join(
                f"{la} ×{c}" for la, c in sorted(lang_counts.items(), key=lambda x: -x[1])
            )
            lines.append(f"## {top_dir}/  ({len(files)} files — {lang_str})")
            for f in sorted(files, key=lambda x: x["path"]):
                ec = entity_counts.get(f["path"], {})
                tags: list[str] = []
                if ec.get("class"):
                    tags.append(f"{ec['class']}cl")
                if ec.get("function"):
                    tags.append(f"{ec['function']}fn")
                if ec.get("method"):
                    tags.append(f"{ec['method']}mt")
                tag_str = f"  [{' '.join(tags)}]" if tags else ""
                lines.append(f"  {f['path']}{tag_str}")

        if len(file_rows) > self._MAX_FILES:
            lines.append(
                f"\n[{len(file_rows) - self._MAX_FILES} additional files omitted — "
                "use file_reader or semantic_search for specific files]"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class _CypherInput(BaseModel):
    query: str = Field(description="Cypher query string to execute against Neo4j")


class _McpCypherWrapper(BaseTool):
    """Wrapper around an MCP cypher tool that provides a proper input schema.

    The neo4j MCP server exposes ``read-cypher`` and ``write-cypher`` with empty
    input schemas.  This wrapper declares the ``query`` parameter so the LLM
    knows which argument name to use.
    """

    args_schema: type[BaseModel] = _CypherInput
    mcp_tool: Any = Field(exclude=True)  # original MCP BaseTool
    get_schema_tool: Any = Field(default=None, exclude=True)  # unused, kept for compat

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _MAX_OUTPUT_CHARS: int = 4000

    async def _arun(self, query: str) -> str:
        result = str(await self.mcp_tool.ainvoke({"query": query}))
        if len(result) > self._MAX_OUTPUT_CHARS:
            result = (
                result[: self._MAX_OUTPUT_CHARS]
                + f"\n[truncated — {len(result)} chars total]"
            )
        return result

    def _run(self, query: str) -> str:
        raise NotImplementedError("Use async invocation (_arun)")


_MCP_WRITE_TOOLS = {"write-cypher"}


def _wrap_mcp_tools(raw_tools: list[BaseTool]) -> list[BaseTool]:
    """Replace MCP cypher tools with wrappers that expose proper schemas.

    ``write-cypher`` is always excluded — the agent is read-only with respect
    to the graph so it cannot accidentally mutate ingested data.

    For read-cypher, we inject the get-schema tool to enable smart schema-aware queries.
    """
    wrapped: list[BaseTool] = []
    # Find the get-schema tool for injection into read-cypher
    get_schema_tool = None
    for tool in raw_tools:
        if tool.name == "get-schema":
            get_schema_tool = tool
            break

    for tool in raw_tools:
        if tool.name in _MCP_WRITE_TOOLS:
            logger.info("MCP: skipping write tool %r (read-only mode)", tool.name)
            continue
        if tool.name == "read-cypher":
            wrapper = _McpCypherWrapper(
                name=tool.name,
                description=tool.description,
                mcp_tool=tool,
                get_schema_tool=get_schema_tool,
            )
            wrapped.append(wrapper)
        else:
            wrapped.append(tool)
    return wrapped


async def get_mcp_tools(settings: Settings | None = None) -> list[BaseTool]:
    """Load tools from the Neo4j MCP server via HTTP.

    Connects to the ``mcp-neo4j`` container running in HTTP transport mode and
    converts its tools into LangChain :class:`~langchain_core.tools.BaseTool`
    instances.  Cypher tools are wrapped with proper input schemas so the LLM
    uses the correct ``query`` parameter name.

    Args:
        settings: Optional settings override; falls back to
            :func:`~aquila_atlas.config.get_settings`.

    Returns:
        List of LangChain tools backed by the MCP server.
    """
    import base64  # noqa: PLC0415

    from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    logger.info("MCP: connecting to neo4j MCP server at %s", s.mcp_url)
    creds = base64.b64encode(f"{s.neo4j_user}:{s.neo4j_password}".encode()).decode()
    client = MultiServerMCPClient(
        {
            "neo4j": {
                "transport": "streamable_http",
                "url": s.mcp_url,
                "headers": {"Authorization": f"Basic {creds}"},
            }
        }
    )
    raw_tools = await client.get_tools()
    tools = _wrap_mcp_tools(raw_tools)
    logger.info("MCP: loaded %d tools — %s", len(tools), [t.name for t in tools])
    return tools


def get_tools(
    service: KnowledgeService,
    settings: Settings | None = None,
) -> list[BaseTool]:
    """Build all reasoning tools with injected service and LLM client.

    Args:
        service: Initialised :class:`~aquila_atlas.knowledge.service.KnowledgeService`.
        settings: Optional settings override; falls back to :func:`~aquila_atlas.config.get_settings`.

    Returns:
        List of LangChain :class:`~langchain_core.tools.BaseTool` instances ready
        to be bound to an agent.
    """
    import openai  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    llm = openai.OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)
    # Graph traversal and direct cypher queries are handled via MCP tools
    # (get-schema/read-cypher/write-cypher) to avoid building cypher in local tools.
    return [
        # High-level composite tools — answer broad questions in one call
        RepoOverviewTool(service=service),
        ModuleMapTool(service=service),
        # Core search and reading
        SemanticSearchTool(service=service),
        FileReaderTool(service=service),
        SummaryTool(service=service, llm=llm),
        DocGenerationTool(service=service, llm=llm),
        MermaidGeneratorTool(service=service, llm=llm),
        ValidateMermaidTool(),
        # Graph-traversal tools — expose Neo4j relationships without raw Cypher
        ListLibsTool(service=service),
        FindCallersTool(service=service),
        ListEntryPointsTool(service=service),
        CallChainTool(service=service),
        # Git tools — read-only; gracefully handle no-.git and remote repos
        GitLogTool(service=service),
        GitStatusTool(service=service),
        GitDiffTool(service=service),
        GitBlameTool(service=service),
    ]
