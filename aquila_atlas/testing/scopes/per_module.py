"""Per-module scope: one test file per top-level directory/package."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

from .._frameworks import detect_language, get_framework
from .._helpers import (
    _code_context,
    _files_in_module,
    _graph_hints,
    _list_modules,
    _list_source_files,
)
from .._prompts import _PROMPT_PER_MODULE, _apply_template
from .._validator import run_fix_loop
from ..generator import GenerationCancelled

logger = logging.getLogger("aquila.test_generator")

_MAX_FILES_PER_MODULE = 8
_MAX_CTX_CHARS = 6000


def _generate_per_module(
    svc: KnowledgeService,
    repo_id: str,
    language_filter: list[str] | None,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
    statuses: dict[str, str] | None = None,
) -> dict[str, str]:
    all_files = _list_source_files(svc, repo_id, exclude_extensions, language_filter)
    modules = _list_modules(svc, repo_id, exclude_extensions, language_filter)

    total = len(modules)
    result: dict[str, str] = {}

    try:
        for i, module in enumerate(modules):
            progress_callback and progress_callback(i, total, module)

            module_files = _files_in_module(all_files, module)
            if not module_files:
                continue

            language = _dominant_language(module_files)
            if language is None:
                continue
            fw = get_framework(language)
            if fw is None or fw.is_stub:
                continue

            ctx_parts: list[str] = []
            imports_parts: list[str] = []
            defines_parts: list[str] = []
            for fp in module_files[:_MAX_FILES_PER_MODULE]:
                chunk = _code_context(svc, repo_id, fp)
                if chunk:
                    ctx_parts.append(f"## {fp}\n{chunk}")
                imp, defs = _graph_hints(svc, repo_id, fp)
                if imp:
                    imports_parts.append(imp)
                if defs:
                    defines_parts.append(defs)

            code_ctx = "\n\n".join(ctx_parts)[:_MAX_CTX_CHARS]
            imports_block = "\n".join(imports_parts)
            defines_block = "\n".join(defines_parts)
            file_list = "\n".join(f"- `{fp}`" for fp in module_files)

            output_path = _module_test_output(module, language, fw.file_ext)

            prompt = _apply_template(
                _PROMPT_PER_MODULE,
                module=module,
                repo_id=repo_id,
                language=fw.language_display,
                framework=fw.framework,
                output_path=output_path,
                file_list=file_list,
                imports_block=imports_block,
                defines_block=defines_block,
                code_ctx=code_ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("test_generator: skipping module %r — LLM error: %s", module, exc)
                content = f"# Could not generate tests for module {module}\n# Error: {exc}\n"
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
            "test_generator: per_module cancelled — returning %d/%d modules",
            len(result),
            total,
        )
        raise GenerationCancelled(
            result, dict(statuses) if statuses is not None else None
        ) from None

    progress_callback and progress_callback(total, total, None)
    return result


def _dominant_language(files: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for f in files:
        lang = detect_language(f)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else None


def _module_test_output(module: str, language: str, ext: str) -> str:
    lang = language.lower()
    if lang == "python":
        return f"tests/{module}/test_{module}.py"
    if lang in ("typescript", "javascript"):
        out_ext = ".ts" if lang == "typescript" else ".js"
        return f"src/__tests__/{module}.test{out_ext}"
    if lang == "java":
        cap = module[0].upper() + module[1:]
        return f"src/test/java/{cap}Test.java"
    if lang == "go":
        return f"{module}/{module}_test.go"
    if lang == "rust":
        return f"tests/{module}.rs"
    if lang in ("c#", "csharp"):
        cap = module[0].upper() + module[1:]
        return f"{cap}Tests.cs"
    if lang == "ruby":
        return f"spec/{module}_spec.rb"
    if lang == "kotlin":
        cap = module[0].upper() + module[1:]
        return f"{cap}Test.kt"
    if lang == "php":
        cap = module[0].upper() + module[1:]
        return f"tests/{cap}Test.php"
    if lang == "swift":
        cap = module[0].upper() + module[1:]
        return f"{cap}Tests.swift"
    if lang == "scala":
        cap = module[0].upper() + module[1:]
        return f"{cap}Spec.scala"
    if lang in ("bash", "shell"):
        return f"test_{module}.bats"
    return f"tests/{module}_test{ext}"
