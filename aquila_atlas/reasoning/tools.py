"""LangChain tool wrappers for the Aquila-Atlas reasoning layer.

Each tool wraps a capability from the knowledge layer (vector search, graph
traversal, file reading) or calls the LLM directly (summarisation, doc gen).
Tools are injected with a :class:`~aquila_atlas.knowledge.service.KnowledgeService`
instance and — where LLM calls are needed — an :class:`openai.OpenAI` client.
"""

from __future__ import annotations

import logging
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
            preview = r.content[:500] + ("..." if len(r.content) > 500 else "")
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

    def _run(self, file_path: str, repo_id: str) -> str:
        logger.debug("tool=file_reader repo=%s path=%r", repo_id, file_path)
        svc = cast("KnowledgeService", self.service)
        # Use the file path as the query so BM25 matches token overlap
        results = svc.search(query=file_path, repo_id=repo_id, top_k=50, file_path=file_path)
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
        return header + "\n\n---\n\n".join(sections)


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
            validate_with_mermaid_py,
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

        # ── 3. LLM generate → mermaid-py validate → feedback loop ─────────
        # The LLM generates the diagram. If mermaid-py (or the Python
        # fallback validator) finds errors, the errors are added to the
        # conversation and the LLM tries again.  Repeat up to MAX_ATTEMPTS.
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

            errors = validate_with_mermaid_py(diagram)
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
        from aquila_atlas.reasoning.mermaid import validate_mermaid  # noqa: PLC0415

        errors = validate_mermaid(diagram)
        if not errors:
            return "valid"
        return "Syntax errors found:\n" + "\n".join(f"- {e}" for e in errors)


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
    get_schema_tool: Any = Field(default=None, exclude=True)  # optional get-schema tool

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def _arun(self, query: str) -> str:
        # Smart approach: for read-cypher queries, first get schema context
        # to help with query understanding and result interpretation
        if self.mcp_tool.name == "read-cypher" and self.get_schema_tool:
            logger.debug("tool=read-cypher: calling get-schema first for context")
            try:
                schema_result = await self.get_schema_tool.ainvoke({})
                logger.debug("tool=read-cypher: schema retrieved (%d chars)", len(schema_result))
                # We don't return the schema, just ensure it's called for context
                # The agent will have this information available through the tool call history
            except Exception as e:
                logger.warning("tool=read-cypher: failed to get schema: %s", e)
                # Continue with the query even if schema fails

        return str(await self.mcp_tool.ainvoke({"query": query}))

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
        SemanticSearchTool(service=service),
        FileReaderTool(service=service),
        SummaryTool(service=service, llm=llm),
        DocGenerationTool(service=service, llm=llm),
        MermaidGeneratorTool(service=service, llm=llm),
        ValidateMermaidTool(),
    ]
