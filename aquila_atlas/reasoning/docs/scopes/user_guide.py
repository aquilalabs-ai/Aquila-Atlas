"""User guide scope generator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._helpers import (
    _build_architecture_graph_context,
    _list_files,
    _search_context,
)
from .._mermaid_fix import _fix_mermaid_blocks
from .._prompts import _LANGUAGE_NAMES, _PROMPT_USER_GUIDE, _STYLE_DESC, _apply_template


def _generate_user_guide(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    progress_callback and progress_callback(0, 1, "user_guide")
    lang_name = _LANGUAGE_NAMES.get(language, "English")
    ctx = _search_context(
        svc, repo_id, "installation setup configuration usage commands features", top_k=20
    )
    graph_ctx = _build_architecture_graph_context(svc, repo_id, exclude_extensions)
    files = _list_files(svc, repo_id, exclude_extensions)

    file_list = "\n".join(f"- {f}" for f in files[:50])
    if len(files) > 50:
        file_list += "\n..."
    prompt = _apply_template(
        _PROMPT_USER_GUIDE,
        repo_id=repo_id,
        lang_name=lang_name,
        style_description=_STYLE_DESC["user_guide"].get(style, style),
        file_count=str(len(files)),
        file_list=file_list,
        graph_ctx=graph_ctx,
        ctx=ctx,
    )
    result = llm.invoke(prompt)
    content: str = result.content if hasattr(result, "content") else str(result)
    content = _fix_mermaid_blocks(content, llm)
    progress_callback and progress_callback(1, 1, None)
    return {"user_guide.md": content}
