"""FindCallersTool — find all callers of a function/method/class via graph traversal."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
