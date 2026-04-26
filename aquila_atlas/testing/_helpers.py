"""Shared helpers for the test generator."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

from aquila_atlas.reasoning.docs._helpers import (
    _ALWAYS_SKIP_NAMES,
    _DEFAULT_SKIP_EXTENSIONS,
    _topological_sort,
)

logger = logging.getLogger("aquila.test_generator")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


def _list_source_files(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
    language_filter: list[str] | None = None,
) -> list[str]:
    """Return ingested source files, filtered by extension and optionally by language.

    Skips test files that are already present in the repo (files whose name
    matches test naming conventions) to avoid generating tests-of-tests.
    """
    from ._frameworks import _EXT_TO_LANG  # noqa: PLC0415

    skip_exts = _DEFAULT_SKIP_EXTENSIONS if exclude_extensions is None else exclude_extensions
    all_files = sorted(svc.list_files(repo_id))

    lang_set: frozenset[str] | None = (
        frozenset(lang.lower() for lang in language_filter) if language_filter else None
    )

    def _should_skip(path: str) -> bool:
        norm = path.replace("\\", "/")
        name = pathlib.Path(norm).name
        ext = pathlib.Path(name).suffix.lower()
        if ext in skip_exts or name in _ALWAYS_SKIP_NAMES:
            return True
        # Skip existing test files
        stem = pathlib.Path(name).stem.lower()
        if (
            stem.startswith("test_")
            or stem.endswith("_test")
            or stem.endswith("_spec")
            or stem.endswith("tests")
            or stem.endswith("test")
            or name.endswith(".test.ts")
            or name.endswith(".test.js")
            or name.endswith(".spec.ts")
            or name.endswith(".spec.js")
            or name.endswith("Test.java")
            or name.endswith("Tests.java")
            or name.endswith("Spec.scala")
            or name.endswith("Test.kt")
            or name.endswith("_spec.rb")
        ):
            return True
        # Language filter
        if lang_set is not None:
            detected = _EXT_TO_LANG.get(ext)
            if detected is None or detected not in lang_set:
                return True
        return False

    return [f for f in all_files if not _should_skip(f)]


def _list_modules(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
    language_filter: list[str] | None = None,
) -> list[str]:
    files = _list_source_files(svc, repo_id, exclude_extensions, language_filter)
    seen: set[str] = set()
    modules: list[str] = []
    for f in files:
        top = f.replace("\\", "/").split("/")[0]
        if top not in seen:
            seen.add(top)
            modules.append(top)
    return modules


def _files_in_module(files: list[str], module: str) -> list[str]:
    return [f for f in files if f.replace("\\", "/").split("/")[0] == module]


def _code_context(svc: KnowledgeService, repo_id: str, file_path: str, top_k: int = 12) -> str:
    results = svc.search(file_path, repo_id, top_k=top_k, file_path=file_path)
    if not results:
        # Fallback to keyword search
        results = svc.search(f"code in {file_path}", repo_id, top_k=top_k)
    if not results:
        return ""
    parts: list[str] = []
    for r in results:
        header = f"### {r.qualified_name} ({r.chunk_type}) — lines {r.start_line}-{r.end_line}"
        parts.append(f"{header}\n```\n{r.content}\n```")
    return "\n\n".join(parts)


def _graph_hints(svc: KnowledgeService, repo_id: str, file_path: str) -> tuple[str, str]:
    """Return (imports_block, defines_block) markdown strings for a file.

    The imports block lists **top-level** imports only (not lazy imports inside
    function bodies).  This is important for test generation: only top-level
    imports can be patched with ``monkeypatch.setattr(module, "name", mock)``.
    Anything the source imports lazily (inside a ``def`` or ``__init__``) will
    NOT appear here and must be patched via ``sys.modules`` instead.
    """
    ctx = svc.get_file_graph_context(repo_id, file_path)
    if not ctx:
        return "", ""

    imports_block = ""
    if ctx.get("imports"):
        lines = [f"- `{p}`" for p in ctx["imports"][:15]]
        imports_block = (
            "**Top-level imports** (safe to patch with `monkeypatch.setattr`):\n"
            + "\n".join(lines)
            + "\n\n> Any dependency imported *inside a function or method body* "
            'will NOT appear above. Patch those via `sys.modules["X"] = mock` '
            'or `unittest.mock.patch("X.symbol")` instead.'
        )

    callees_block = ""
    defines = ctx.get("defines", [])
    if defines:
        callees_block = "**Defines:**\n" + "\n".join(f"- `{s}`" for s in defines[:20])

    return imports_block, callees_block


__all__ = [
    "_DEFAULT_SKIP_EXTENSIONS",
    "_topological_sort",
    "_list_source_files",
    "_list_modules",
    "_files_in_module",
    "_code_context",
    "_graph_hints",
]
