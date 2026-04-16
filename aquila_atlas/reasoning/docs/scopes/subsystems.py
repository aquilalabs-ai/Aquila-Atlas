"""Subsystems scope generator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._helpers import _detect_subsystems, _name_subsystem, _search_context
from .._prompts import _LANGUAGE_NAMES, _PROMPT_SUBSYSTEMS, _STYLE_DESC, _apply_template
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.docs_generator")


def _generate_subsystems(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    subsystems = _detect_subsystems(svc, repo_id, exclude_extensions)
    total = len(subsystems)
    result: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, files in enumerate(subsystems):
            name = _name_subsystem(files)
            progress_callback and progress_callback(i, total, name)

            # Identify public interface: files with high in-degree
            all_edges = svc.get_import_graph(repo_id)
            in_counts: dict[str, int] = {}
            for _, tgt in all_edges:
                if tgt in files:
                    in_counts[tgt] = in_counts.get(tgt, 0) + 1
            public_files = sorted(in_counts, key=lambda f: -in_counts[f])[:5]

            ctx = _search_context(svc, repo_id, f"subsystem {name} components interface", top_k=15)

            public_files_text = (
                "\n".join(f"- {f} (imported by {in_counts.get(f, 0)} files)" for f in public_files)
                if public_files
                else "(none detected)"
            )
            prompt = _apply_template(
                _PROMPT_SUBSYSTEMS,
                name=name,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["subsystems"].get(style, style),
                file_count=str(len(files)),
                files="\n".join(f"- {f}" for f in files),
                public_files=public_files_text,
                ctx=ctx,
            )
            out = llm.invoke(prompt)
            content: str = out.content if hasattr(out, "content") else str(out)
            result[f"subsystems/{name.replace(chr(92), '/')}.md"] = content
    except GenerationCancelled:
        logger.info(
            "docs_generator: subsystem cancelled — returning %d/%d subsystems", len(result), total
        )
        raise GenerationCancelled(result)

    progress_callback and progress_callback(total, total, None)
    return result
