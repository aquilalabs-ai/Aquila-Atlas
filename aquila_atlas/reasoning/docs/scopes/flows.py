"""Flows scope generator."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._helpers import _search_context
from .._prompts import _LANGUAGE_NAMES, _PROMPT_FLOWS, _STYLE_DESC, _apply_template
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.docs_generator")

# Name prefixes that signal an important orchestration/entry function
_ENTRY_NAME_PREFIXES: tuple[str, ...] = (
    "main",
    "run",
    "start",
    "execute",
    "process",
    "handle",
    "dispatch",
    "serve",
    "launch",
    "init",
    "setup",
    "bootstrap",
    "invoke",
    "cli",
    "command",
)

# File stems that are strong signals for top-level entry points
_ENTRY_FILE_STEMS: frozenset[str] = frozenset(
    {
        "__main__",
        "main",
        "cli",
        "app",
        "server",
        "run",
        "manage",
        "wsgi",
        "asgi",
        "entrypoint",
        "entry_point",
        "start",
        "bootstrap",
        "launcher",
    }
)

# Maximum entry points to document per top-level module
_MAX_EPS_PER_MODULE = 3
# Absolute cap on total flows documented
_MAX_FLOWS_TOTAL = 20


def _score_entry_point(ep: dict[str, Any]) -> float:
    """Assign a float importance score to an entry point dict.

    Higher score → more important to document.  Scoring factors:

    - **out_degree** (calls-out count): orchestrators call many things.
    - **name heuristics**: common entry-point verb prefixes get a bonus.
    - **file-stem heuristics**: files like ``main.py``, ``cli.py`` get a bonus.
    """
    score: float = float(ep.get("out_degree") or 0)

    name_lower = str(ep.get("name", "")).split("::")[-1].lower().replace("-", "_")
    if any(name_lower == p or name_lower.startswith(f"{p}_") for p in _ENTRY_NAME_PREFIXES):
        score += 5.0

    file_path = str(ep.get("file_path", "")).replace("\\", "/")
    stem = file_path.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    if stem.lower() in _ENTRY_FILE_STEMS:
        score += 4.0

    return score


def _select_entry_points(
    entry_points: list[dict[str, Any]],
    exclude_extensions: frozenset[str] | None,
) -> list[dict[str, Any]]:
    """Filter, score, group, and cap entry points for flow documentation.

    Strategy:
    1. Drop files matching excluded extensions.
    2. Score each entry point.
    3. Group by top-level module (first path segment).
    4. Within each module keep the top *_MAX_EPS_PER_MODULE* by score.
    5. Sort the surviving entries by score descending.
    6. Hard-cap at *_MAX_FLOWS_TOTAL*.

    Returns the selected entry points ordered by importance (highest first).
    """
    # Extension filter
    filtered = (
        [
            ep
            for ep in entry_points
            if not any(ep["file_path"].lower().endswith(ext) for ext in exclude_extensions)
        ]
        if exclude_extensions
        else list(entry_points)
    )

    if not filtered:
        return []

    # Score everything
    scored = [(ep, _score_entry_point(ep)) for ep in filtered]

    # Group by top-level module
    by_module: dict[str, list[tuple[dict[str, Any], float]]] = {}
    for ep, sc in scored:
        module = ep["file_path"].replace("\\", "/").split("/")[0]
        by_module.setdefault(module, []).append((ep, sc))

    # Keep top N per module
    selected: list[tuple[dict[str, Any], float]] = []
    for module_eps in by_module.values():
        module_eps.sort(key=lambda x: -x[1])
        selected.extend(module_eps[:_MAX_EPS_PER_MODULE])

    # Global sort by score and cap
    selected.sort(key=lambda x: -x[1])
    selected = selected[:_MAX_FLOWS_TOTAL]

    logger.info(
        "docs_generator: entry-point selection — %d raw → %d after scoring/cap",
        len(filtered),
        len(selected),
    )
    return [ep for ep, _ in selected]


def _generate_flows(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    raw_entry_points = svc.get_entry_points(repo_id)
    entry_points = _select_entry_points(raw_entry_points, exclude_extensions)

    if not entry_points:
        msg = (
            "# No meaningful entry points found\n\n"
            "No public functions without callers were detected in this repository, "
            "or all candidates were filtered out.\n\n"
            "**Possible reasons**\n"
            "- The language parser for this codebase does not extract CALLS edges.\n"
            "- All public functions are called by other code in the repo (no true entry points).\n"
            "- The codebase uses dynamic dispatch or decorators that hide call relationships.\n\n"
            "Try the `architecture` or `per_module` scope instead for broader coverage."
        )
        return {"flows/no_entry_points.md": msg}

    total = len(entry_points)
    result: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, ep in enumerate(entry_points):
            name = ep["name"]
            file_path = ep["file_path"]
            out_degree = ep.get("out_degree", 0)
            progress_callback and progress_callback(i, total, name)

            # Build start_id: repo_id:file_path:qualified_name format
            start_id = f"{repo_id}:{file_path}:{name}"
            call_chain: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                call_chain = svc.get_call_chain(repo_id, start_id, max_depth=6)

            # Build call tree text
            tree_lines: list[str] = [
                f"- `{name}` (depth 0) — entry point in `{file_path}`"
                + (f" [calls {out_degree} direct children]" if out_degree else "")
            ]
            for step in call_chain:
                indent = "  " * int(step.get("depth", 1))
                tree_lines.append(
                    f"{indent}- `{step['name']}` (depth {step['depth']}) in `{step['file_path']}`"
                )
            call_tree = "\n".join(tree_lines)

            ctx = _search_context(svc, repo_id, f"function {name} {file_path}", top_k=10)

            prompt = _apply_template(
                _PROMPT_FLOWS,
                name=name,
                file_path=file_path,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["flows"].get(style, style),
                call_count=str(len(call_chain)),
                call_tree=call_tree,
                ctx=ctx,
            )
            out = llm.invoke(prompt)
            content: str = out.content if hasattr(out, "content") else str(out)
            doc_dir = file_path.replace("\\", "/").removesuffix(".py")
            safe_func = name.replace(".", "_")
            result[f"flows/{doc_dir}/{safe_func}.md"] = content
    except GenerationCancelled:
        logger.info("docs_generator: flows cancelled — returning %d/%d flows", len(result), total)
        raise GenerationCancelled(result) from None

    progress_callback and progress_callback(total, total, None)
    return result
