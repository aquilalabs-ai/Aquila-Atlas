"""ListEntryPointsTool — list all public entry-point functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
