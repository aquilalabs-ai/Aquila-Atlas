"""Per-file scope generator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._helpers import (
    _extract_summary,
    _graph_context_block,
    _list_files,
    _search_context,
    _topological_sort,
)
from .._prompts import _LANGUAGE_NAMES, _PROMPT_PER_FILE, _STYLE_DESC, _apply_template
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.docs_generator")


def _generate_per_file(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    files = _list_files(svc, repo_id, exclude_extensions)
    edges = svc.get_import_graph(repo_id)
    ordered = _topological_sort(files, edges)

    total = len(ordered)
    result: dict[str, str] = {}
    dependency_summaries: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, file_path in enumerate(ordered):
            progress_callback and progress_callback(i, total, file_path)
            ctx = _search_context(svc, repo_id, file_path, top_k=10)
            graph_ctx = _graph_context_block(svc, repo_id, file_path)

            # Inject summaries from dependencies already documented
            dep_summaries: list[str] = []
            for src, tgt in edges:
                if src == file_path and tgt in dependency_summaries:
                    dep_summaries.append(f"- `{tgt}`: {dependency_summaries[tgt]}")
            dep_section = (
                ("\n**Already-documented dependencies:**\n" + "\n".join(dep_summaries))
                if dep_summaries
                else ""
            )

            prompt = _apply_template(
                _PROMPT_PER_FILE,
                file_path=file_path,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["per_file"].get(style, style),
                graph_ctx=graph_ctx,
                dep_section=dep_section,
                ctx=ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("docs_generator: skipping file %r — LLM error: %s", file_path, exc)
                content = f"# {file_path}\n\n> ⚠️ Documentation could not be generated for this file: `{exc}`\n"
            doc_path = file_path.replace("\\", "/")
            stem, ext = (
                doc_path.rsplit(".", 1) if "." in doc_path.split("/")[-1] else (doc_path, "")
            )
            if ext and ext not in ("md", "txt", "rst"):
                doc_path = stem + ".md"
            result[doc_path] = content
            dependency_summaries[file_path] = _extract_summary(content)
    except GenerationCancelled:
        logger.info(
            "docs_generator: per_file cancelled — returning %d/%d files", len(result), total
        )
        raise GenerationCancelled(result) from None

    progress_callback and progress_callback(total, total, None)
    return result
