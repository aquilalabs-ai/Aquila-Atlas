"""ListLibsTool — list all external libraries imported by the codebase."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
