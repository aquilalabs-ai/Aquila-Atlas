"""CallChainTool — trace the call chain starting from a given function."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
