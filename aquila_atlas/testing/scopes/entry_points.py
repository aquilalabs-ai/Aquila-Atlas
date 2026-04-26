"""Entry-points scope: tests for scored public functions with no callers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

# Re-use the scoring/selection logic from docs flows scope
from aquila_atlas.reasoning.docs.scopes.flows import _score_entry_point

from .._frameworks import detect_language, get_framework
from .._helpers import _list_source_files
from .._prompts import _PROMPT_ENTRY_POINTS, _apply_template
from .._validator import run_fix_loop
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.test_generator")

_MAX_EPS_PER_MODULE = 3
_MAX_EPS_TOTAL = 20


def _select_entry_points(
    entry_points: list[dict[str, Any]],
    available_files: set[str],
    language_filter: list[str] | None,
) -> list[dict[str, Any]]:
    lang_set = frozenset(lang.lower() for lang in language_filter) if language_filter else None

    filtered: list[dict[str, Any]] = []
    for ep in entry_points:
        fp = ep.get("file_path", "")
        if fp not in available_files:
            continue
        if lang_set is not None:
            lang = detect_language(fp)
            if lang is None or lang not in lang_set:
                continue
        filtered.append(ep)

    if not filtered:
        return []

    scored = [(ep, _score_entry_point(ep)) for ep in filtered]
    by_module: dict[str, list[tuple[dict[str, Any], float]]] = {}
    for ep, sc in scored:
        module = ep["file_path"].replace("\\", "/").split("/")[0]
        by_module.setdefault(module, []).append((ep, sc))

    selected: list[tuple[dict[str, Any], float]] = []
    for module_eps in by_module.values():
        module_eps.sort(key=lambda x: -x[1])
        selected.extend(module_eps[:_MAX_EPS_PER_MODULE])

    selected.sort(key=lambda x: -x[1])
    selected = selected[:_MAX_EPS_TOTAL]
    return [ep for ep, _ in selected]


def _generate_entry_points(
    svc: KnowledgeService,
    repo_id: str,
    language_filter: list[str] | None,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
    statuses: dict[str, str] | None = None,
) -> dict[str, str]:
    available_files = set(_list_source_files(svc, repo_id, exclude_extensions, language_filter))

    raw_eps = svc.get_entry_points(repo_id)
    entry_points = _select_entry_points(raw_eps, available_files, language_filter)

    if not entry_points:
        return {
            "tests/no_entry_points.md": (
                "# No entry points found\n\n"
                "No public functions without callers were detected for the selected language(s).\n\n"
                "Try the `per_file` or `per_module` scope for broader coverage."
            )
        }

    total = len(entry_points)
    result: dict[str, str] = {}

    try:
        for i, ep in enumerate(entry_points):
            name = ep["name"]
            file_path = ep["file_path"]
            progress_callback and progress_callback(i, total, f"{name} ({file_path})")

            language = detect_language(file_path)
            if language is None:
                continue
            fw = get_framework(language)
            if fw is None or fw.is_stub:
                continue

            results = svc.search(
                f"function {name} implementation",
                repo_id,
                top_k=8,
                file_path=file_path,
            )
            code_ctx = "\n\n".join(
                f"### {r.qualified_name} ({r.chunk_type})\n```\n{r.content}\n```" for r in results
            )

            out_degree = ep.get("out_degree", 0)
            output_path = _ep_test_output(name, file_path, language, fw.file_ext)

            prompt = _apply_template(
                _PROMPT_ENTRY_POINTS,
                function_name=name,
                file_path=file_path,
                repo_id=repo_id,
                language=fw.language_display,
                framework=fw.framework,
                output_path=output_path,
                out_degree=str(out_degree),
                code_ctx=code_ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("test_generator: skipping entry point %r — LLM error: %s", name, exc)
                content = f"# Could not generate tests for {name}\n# Error: {exc}\n"
                result[output_path] = content
                if statuses is not None:
                    statuses[output_path] = "unvalidated"
                continue

            content, status = run_fix_loop(output_path, content, llm, fw.language_display)
            result[output_path] = content
            if statuses is not None:
                statuses[output_path] = status

    except GenerationCancelled:
        logger.info("test_generator: entry_points cancelled — returning %d/%d", len(result), total)
        raise GenerationCancelled(
            result, dict(statuses) if statuses is not None else None
        ) from None

    progress_callback and progress_callback(total, total, None)
    return result


def _ep_test_output(name: str, file_path: str, language: str, ext: str) -> str:
    """Derive a test output path for a specific entry-point function."""
    import pathlib  # noqa: PLC0415

    norm = file_path.replace("\\", "/")
    p = pathlib.PurePosixPath(norm)
    dir_part = str(p.parent) if str(p.parent) != "." else ""
    safe_name = name.replace("::", "_").replace(".", "_")

    lang = language.lower()
    if lang == "python":
        prefix = f"{dir_part}/" if dir_part else ""
        return f"tests/{prefix}test_{safe_name}.py"
    if lang in ("typescript", "javascript"):
        out_ext = ".ts" if lang == "typescript" else ".js"
        return f"src/__tests__/{safe_name}.test{out_ext}"
    if lang == "java":
        cap = safe_name[0].upper() + safe_name[1:]
        prefix = dir_part.replace("src/main/java", "src/test/java", 1)
        return f"{prefix}/{cap}Test.java" if prefix else f"src/test/java/{cap}Test.java"
    if lang == "go":
        prefix = f"{dir_part}/" if dir_part else ""
        return f"{prefix}{safe_name}_test.go"
    if lang == "rust":
        return f"tests/{safe_name}.rs"
    if lang in ("c#", "csharp"):
        cap = safe_name[0].upper() + safe_name[1:]
        return f"{cap}Tests.cs"
    if lang == "ruby":
        return f"spec/{safe_name}_spec.rb"
    if lang == "kotlin":
        cap = safe_name[0].upper() + safe_name[1:]
        return f"{cap}Test.kt"
    if lang == "php":
        cap = safe_name[0].upper() + safe_name[1:]
        return f"tests/{cap}Test.php"
    if lang == "swift":
        cap = safe_name[0].upper() + safe_name[1:]
        return f"{cap}Tests.swift"
    if lang == "scala":
        cap = safe_name[0].upper() + safe_name[1:]
        return f"{cap}Spec.scala"
    if lang in ("bash", "shell"):
        return f"test_{safe_name}.bats"
    return f"tests/{safe_name}_test{ext}"
