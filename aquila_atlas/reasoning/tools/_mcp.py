"""MCP tool wrappers and loader for the neo4j MCP server."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.config import Settings


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
            result = result[: self._MAX_OUTPUT_CHARS] + f"\n[truncated — {len(result)} chars total]"
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
