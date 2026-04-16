"""LangChain tool wrappers for the Aquila-Atlas reasoning layer.

Each tool wraps a capability from the knowledge layer (vector search, graph
traversal, file reading) or calls the LLM directly (summarisation, doc gen).
Tools are injected with a :class:`~aquila_atlas.knowledge.service.KnowledgeService`
instance and — where LLM calls are needed — an :class:`openai.OpenAI` client.
"""

from __future__ import annotations

from ._base import _llm_complete
from ._mcp import (
    _CypherInput,
    _McpCypherWrapper,
    _MCP_WRITE_TOOLS,
    _wrap_mcp_tools,
    get_mcp_tools,
)
from .call_chain import CallChainInput, CallChainTool
from .docstring import DocGenerationInput, DocGenerationTool
from .entry_points import ListEntryPointsInput, ListEntryPointsTool
from .factory import get_tools
from .file_reader import FileReaderInput, FileReaderTool
from .find_callers import FindCallersInput, FindCallersTool
from .git import (
    GitBlameInput,
    GitBlameTool,
    GitDiffInput,
    GitDiffTool,
    GitLogInput,
    GitLogTool,
    GitStatusInput,
    GitStatusTool,
)
from .list_libs import ListLibsInput, ListLibsTool
from .mermaid import (
    MermaidGeneratorTool,
    MermaidInput,
    ValidateMermaidInput,
    ValidateMermaidTool,
    _format_graph_data,
    _MERMAID_CYPHER,
    _MERMAID_GEN_SYSTEM,
)
from .module_map import ModuleMapInput, ModuleMapTool
from .repo_overview import (
    RepoOverviewInput,
    RepoOverviewTool,
    _PRIORITY_FILE_STEMS,
    _PRIORITY_PREFIXES,
    _score_entry_point,
)
from .semantic_search import SemanticSearchInput, SemanticSearchTool
from .summary import SummaryInput, SummaryTool

__all__ = [
    # Base helper
    "_llm_complete",
    # MCP
    "_CypherInput",
    "_McpCypherWrapper",
    "_MCP_WRITE_TOOLS",
    "_wrap_mcp_tools",
    "get_mcp_tools",
    # Tools
    "SemanticSearchInput",
    "SemanticSearchTool",
    "FileReaderInput",
    "FileReaderTool",
    "SummaryInput",
    "SummaryTool",
    "DocGenerationInput",
    "DocGenerationTool",
    "MermaidInput",
    "ValidateMermaidInput",
    "MermaidGeneratorTool",
    "ValidateMermaidTool",
    "_MERMAID_CYPHER",
    "_MERMAID_GEN_SYSTEM",
    "_format_graph_data",
    "ListLibsInput",
    "ListLibsTool",
    "FindCallersInput",
    "FindCallersTool",
    "ListEntryPointsInput",
    "ListEntryPointsTool",
    "CallChainInput",
    "CallChainTool",
    "RepoOverviewInput",
    "RepoOverviewTool",
    "_score_entry_point",
    "_PRIORITY_PREFIXES",
    "_PRIORITY_FILE_STEMS",
    "ModuleMapInput",
    "ModuleMapTool",
    # Git tools
    "GitLogInput",
    "GitLogTool",
    "GitStatusInput",
    "GitStatusTool",
    "GitDiffInput",
    "GitDiffTool",
    "GitBlameInput",
    "GitBlameTool",
    # Factory
    "get_tools",
]
