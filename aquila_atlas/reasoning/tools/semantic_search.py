"""SemanticSearchTool — hybrid semantic + keyword search over ingested code chunks."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class SemanticSearchInput(BaseModel):
    query: str = Field(description="Natural language search query about the codebase")
    repo_id: str = Field(description="Repository ID to search within")
    top_k: int = Field(default=5, description="Number of results to return (1-20)")
    chunk_type: str | None = Field(
        default=None,
        description="Optionally filter by chunk type: 'file', 'class', 'function', or 'method'",
    )


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
