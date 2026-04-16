"""ModuleMapTool — return the full module/package map of the repository."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
