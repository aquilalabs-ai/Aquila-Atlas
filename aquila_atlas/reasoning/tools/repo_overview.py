"""RepoOverviewTool — one-shot codebase overview: top entry points with call chains."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


_PRIORITY_PREFIXES = ("main", "run", "handle", "start", "execute", "process", "create", "build")
_PRIORITY_FILE_STEMS = ("__main__", "cli", "main", "app", "server", "run")


def _score_entry_point(ep: dict[str, Any]) -> float:
    """Heuristic score for ranking entry points: out-degree + name/file hints."""
    score = float(ep.get("out_degree") or 0)
    name = str(ep.get("name", "")).lower()
    stem = str(ep.get("file_path", "")).split("/")[-1]
    stem = stem.rsplit(".", 1)[0].lower()
    if any(p in name for p in _PRIORITY_PREFIXES):
        score += 5
    if any(p in stem for p in _PRIORITY_FILE_STEMS):
        score += 3
    return score


class RepoOverviewInput(BaseModel):
    repo_id: str = Field(description="Repository ID to overview")
    max_entry_points: int = Field(
        default=3,
        description="Number of top entry points to expand with call chains (1-5).",
    )


class RepoOverviewTool(BaseTool):
    """One-shot codebase overview: top entry points with their call chains.

    Replaces the common ``list_entry_points`` + N × ``call_chain`` pattern by
    doing all the graph work internally and returning a single formatted digest.
    """

    name: str = "repo_overview"
    description: str = (
        "Return a complete codebase overview in ONE call: top entry points and their "
        "call chains (up to depth 3). "
        "Use this FIRST for questions about entry points, main execution flows, or "
        "'how does this codebase work'. "
        "Replaces list_entry_points + call_chain — do NOT call those separately afterwards."
    )
    args_schema: type[BaseModel] = RepoOverviewInput
    service: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str, max_entry_points: int = 3) -> str:
        logger.debug("tool=repo_overview repo=%s max_eps=%d", repo_id, max_entry_points)
        svc = cast("KnowledgeService", self.service)
        max_entry_points = max(1, min(max_entry_points, 5))

        # ── 1. All entry points (ranked by graph, re-scored here) ────────
        all_eps = svc.get_entry_points(repo_id)
        if not all_eps:
            return (
                f"No entry points found for repo '{repo_id}'. "
                "CALLS edges may not be available for this language — "
                "try semantic_search for 'main function' or 'entry point' instead."
            )
        top_eps = sorted(all_eps, key=_score_entry_point, reverse=True)[:max_entry_points]

        # ── 2. Resolve IDs + call chains for the top entry points ────────
        ep_chains: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for ep in top_eps:
            ep_name = str(ep.get("name", ""))
            try:
                rows = svc.graph.cypher_read(
                    """
                    MATCH (fn {repo_id: $repo_id})
                    WHERE (fn:Function OR fn:Method)
                      AND (fn.qualified_name = $name OR fn.name = $name)
                    RETURN fn.id AS id
                    LIMIT 1
                    """,
                    params={"repo_id": repo_id, "name": ep_name},
                )
                chain = svc.get_call_chain(repo_id, str(rows[0]["id"]), max_depth=3) if rows else []
            except Exception as exc:  # noqa: BLE001
                logger.warning("tool=repo_overview chain lookup failed for %r: %s", ep_name, exc)
                chain = []
            ep_chains.append((ep, chain))

        # ── 3. Format ─────────────────────────────────────────────────────
        parts: list[str] = [f"# Entry-point overview for '{repo_id}'\n"]
        parts.append(
            f"Total entry points found: {len(all_eps)} "
            f"(showing top {len(ep_chains)} by significance)\n"
        )

        for ep, chain in ep_chains:
            out_deg = ep.get("out_degree", 0)
            parts.append(
                f"## {ep.get('name', '?')}"
                f"  [{str(ep.get('kind', '?')).lower()}]"
                f"  {ep.get('file_path', '?')}"
                f"  (calls {out_deg} others)"
            )
            if chain:
                by_depth: dict[int, list[str]] = {}
                for step in chain:
                    d = int(step.get("depth", 1))
                    by_depth.setdefault(d, []).append(str(step.get("name", "?")))
                for depth in sorted(by_depth):
                    calls = ", ".join(by_depth[depth][:6])
                    if len(by_depth[depth]) > 6:
                        calls += f" (+{len(by_depth[depth]) - 6} more)"
                    parts.append(f"{'  ' * depth}  depth {depth}: {calls}")
            else:
                parts.append("  (no further calls recorded in graph)")
            parts.append("")

        if len(all_eps) > max_entry_points:
            parts.append(
                f"({len(all_eps) - max_entry_points} more entry points omitted — "
                "call list_entry_points for the full list)"
            )
        return "\n".join(parts)
