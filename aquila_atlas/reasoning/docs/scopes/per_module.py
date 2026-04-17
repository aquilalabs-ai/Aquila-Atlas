"""Per-module scope generator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._helpers import (
    _extract_summary,
    _list_files,
    _list_modules,
    _search_context,
    _topological_sort,
)
from .._prompts import _LANGUAGE_NAMES, _PROMPT_PER_MODULE, _STYLE_DESC, _apply_template
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.docs_generator")


def _generate_per_module(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    modules = _list_modules(svc, repo_id, exclude_extensions)
    all_files = _list_files(svc, repo_id, exclude_extensions)
    edges = svc.get_import_graph(repo_id)

    # Topo-sort at module level
    module_edges: list[tuple[str, str]] = []
    for src, tgt in edges:
        src_mod = src.replace("\\", "/").split("/")[0]
        tgt_mod = tgt.replace("\\", "/").split("/")[0]
        if src_mod != tgt_mod:
            module_edges.append((src_mod, tgt_mod))
    ordered_modules = _topological_sort(modules, module_edges)

    total = len(ordered_modules)
    result: dict[str, str] = {}
    dependency_summaries: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, module in enumerate(ordered_modules):
            progress_callback and progress_callback(i, total, module)
            module_files = [f for f in all_files if f.replace("\\", "/").split("/")[0] == module]
            ctx = _search_context(svc, repo_id, f"module {module} classes functions", top_k=15)

            # Inject summaries from already-generated dependencies
            dep_context = ""
            for src_mod, tgt_mod in module_edges:
                if tgt_mod == module and src_mod in dependency_summaries:
                    dep_context += f"\n**Dependency `{src_mod}`**: {dependency_summaries[src_mod]}"

            prompt = _apply_template(
                _PROMPT_PER_MODULE,
                module=module,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["per_module"].get(style, style),
                file_count=str(len(module_files)),
                module_files="\n".join(f"- {f}" for f in module_files),
                dep_context=dep_context,
                ctx=ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("docs_generator: skipping module %r — LLM error: %s", module, exc)
                content = f"# {module}\n\n> ⚠️ Documentation could not be generated for this module: `{exc}`\n"
            result[f"{module}.md"] = content
            dependency_summaries[module] = _extract_summary(content)
    except GenerationCancelled:
        logger.info(
            "docs_generator: per_module cancelled — returning %d/%d modules", len(result), total
        )
        raise GenerationCancelled(result) from None

    progress_callback and progress_callback(total, total, None)
    return result
