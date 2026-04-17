"""Factory function that builds all reasoning tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService


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

    from .call_chain import CallChainTool
    from .docstring import DocGenerationTool
    from .entry_points import ListEntryPointsTool
    from .file_reader import FileReaderTool
    from .find_callers import FindCallersTool
    from .git import GitBlameTool, GitDiffTool, GitLogTool, GitStatusTool
    from .list_libs import ListLibsTool
    from .mermaid import MermaidGeneratorTool, ValidateMermaidTool
    from .module_map import ModuleMapTool
    from .repo_overview import RepoOverviewTool
    from .semantic_search import SemanticSearchTool
    from .summary import SummaryTool

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
