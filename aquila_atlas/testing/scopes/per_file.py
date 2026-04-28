"""Per-file scope: one test file per source file."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._frameworks import derive_output_path, detect_language, get_framework
from .._helpers import _code_context, _graph_hints, _list_source_files, _topological_sort
from .._prompts import _PROMPT_PER_FILE, _apply_template
from .._validator import run_fix_loop
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.test_generator")


def _generate_per_file(
    svc: KnowledgeService,
    repo_id: str,
    language_filter: list[str] | None,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
    statuses: dict[str, str] | None = None,
) -> dict[str, str]:
    files = _list_source_files(svc, repo_id, exclude_extensions, language_filter)
    edges = svc.get_import_graph(repo_id)
    ordered = _topological_sort(files, edges)

    total = len(ordered)
    result: dict[str, str] = {}

    try:
        for i, file_path in enumerate(ordered):
            progress_callback and progress_callback(i, total, file_path)

            language = detect_language(file_path)
            if language is None:
                logger.debug("test_generator: skipping unknown language file %r", file_path)
                continue

            fw = get_framework(language)
            if fw is None:
                continue

            output_path = derive_output_path(file_path, language)
            imports_block, defines_block = _graph_hints(svc, repo_id, file_path)
            code_ctx = _code_context(svc, repo_id, file_path)

            if fw.is_stub:
                content = _cobol_stub(file_path, output_path)
                result[output_path] = content
                if statuses is not None:
                    statuses[output_path] = "unvalidated"
                continue

            prompt = _apply_template(
                _PROMPT_PER_FILE,
                file_path=file_path,
                repo_id=repo_id,
                language=fw.language_display,
                framework=fw.framework,
                output_path=output_path,
                imports_block=imports_block,
                defines_block=defines_block,
                code_ctx=code_ctx,
            )
            try:
                out = llm.invoke(prompt)
                content = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("test_generator: skipping %r — LLM error: %s", file_path, exc)
                content = f"# Could not generate tests for {file_path}\n# Error: {exc}\n"
                result[output_path] = content
                if statuses is not None:
                    statuses[output_path] = "unvalidated"
                continue

            content, status = run_fix_loop(output_path, content, llm, fw.language_display)
            result[output_path] = content
            if statuses is not None:
                statuses[output_path] = status

    except GenerationCancelled:
        logger.info(
            "test_generator: per_file cancelled — returning %d/%d files", len(result), total
        )
        raise GenerationCancelled(
            result, dict(statuses) if statuses is not None else None
        ) from None

    progress_callback and progress_callback(total, total, None)
    return result


def _cobol_stub(source_path: str, output_path: str) -> str:
    return (
        f"      * Auto-generated test stub for {source_path}\n"
        f"      * Framework: none (COBOL — manual test harness required)\n"
        f"      * Output: {output_path}\n"
        "      *\n"
        "      * TODO: Implement test cases using your COBOL test framework.\n"
        "      * Consider using a batch JCL harness or a third-party tool\n"
        "      * such as COBOL-Check or COBOL Unit Test.\n"
    )
