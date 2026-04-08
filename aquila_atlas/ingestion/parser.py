"""Code parser — extract structured entities from raw source files."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import CodeEntity, Visibility

if TYPE_CHECKING:
    from collections.abc import Iterator

    from aquila_atlas.ingestion.sources import RawFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _visibility(name: str) -> Visibility:
    """Derive visibility from Python naming convention."""
    if name.startswith("__") and not name.endswith("__"):
        return "mangled"
    if name.startswith("_"):
        return "private"
    return "public"


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[str, ...]:
    """Return decorator expressions as strings."""
    return tuple(ast.unparse(dec) for dec in node.decorator_list)


def _extract_imports(tree: ast.Module) -> tuple[str, ...]:
    """Return all top-level imported *modules* as dotted strings.

    For ``import foo.bar`` we record ``foo.bar``.
    For ``from foo.bar import Baz`` we record ``foo.bar`` (the module, not the
    symbol), since ``_resolve_py_import`` maps dotted names to file paths —
    appending the symbol name would produce an unresolvable path like
    ``foo/bar/Baz.py``.
    """
    seen: set[str] = set()
    result: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in seen:
                    seen.add(alias.name)
                    result.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module and module not in seen:
                seen.add(module)
                result.append(module)
    return tuple(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(file: RawFile) -> list[CodeEntity]:
    """Dispatch to the appropriate language plugin, falling back to a single
    file-level entity for unsupported extensions."""
    from aquila_atlas.ingestion.language import get_plugin  # lazy — avoids circular import

    suffix = Path(file.path).suffix.lower()
    plugin = get_plugin(suffix)
    if plugin is not None:
        return plugin.parse_file(file.content, file.path)

    # Unsupported extension: single file-level entity preserving raw text.
    try:
        text = file.content.decode("utf-8")
    except UnicodeDecodeError:
        return []
    line_count = text.count("\n") + (1 if text else 0)
    return [
        CodeEntity(
            type="file",
            name=Path(file.path).name,
            qualified_name=file.path,
            file_path=file.path,
            start_line=1,
            end_line=line_count,
            source=text,
        )
    ]


# ---------------------------------------------------------------------------
# Python parser
# ---------------------------------------------------------------------------


def _get_source_slice(lines: list[str], start: int, end: int) -> str:
    """Return source lines [start, end] (1-based, inclusive)."""
    return "".join(lines[start - 1 : end])


def _end_lineno(node: ast.AST) -> int:
    """Return end_lineno, raising if absent (never happens after ast.parse)."""
    end = getattr(node, "end_lineno", None)
    if end is None:
        raise ValueError(f"Node {node!r} has no end_lineno")
    return int(end)


def _iter_class_entities(
    node: ast.ClassDef,
    lines: list[str],
    file_path: str,
) -> Iterator[CodeEntity]:
    class_name = node.name
    end = _end_lineno(node)
    class_source = _get_source_slice(lines, node.lineno, end)
    yield CodeEntity(
        type="class",
        name=class_name,
        qualified_name=class_name,
        file_path=file_path,
        start_line=node.lineno,
        end_line=end,
        source=class_source,
        docstring=ast.get_docstring(node),
        decorators=_decorators(node),
        visibility=_visibility(class_name),
    )
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            # Only immediate methods (depth-1 inside the class body)
            if child not in node.body:
                continue
            child_end = _end_lineno(child)
            method_source = _get_source_slice(lines, child.lineno, child_end)
            yield CodeEntity(
                type="method",
                name=child.name,
                qualified_name=f"{class_name}.{child.name}",
                file_path=file_path,
                start_line=child.lineno,
                end_line=child_end,
                source=method_source,
                docstring=ast.get_docstring(child),
                parent=class_name,
                decorators=_decorators(child),
                visibility=_visibility(child.name),
                is_async=isinstance(child, ast.AsyncFunctionDef),
            )


def parse_python(source: str, file_path: str) -> list[CodeEntity]:
    """Parse a Python source string and return all code entities."""
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    lines = [line + "\n" for line in source.splitlines()]
    # Correct the last line (splitlines strips the trailing newline)
    if source and not source.endswith("\n") and lines:
        lines[-1] = lines[-1].rstrip("\n")

    total_lines = len(lines) if lines else 1
    stem = Path(file_path).stem

    entities: list[CodeEntity] = [
        CodeEntity(
            type="file",
            name=stem,
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=total_lines,
            source=source,
            docstring=ast.get_docstring(tree),
            imports=_extract_imports(tree),
        )
    ]

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            entities.extend(_iter_class_entities(node, lines, file_path))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_end = _end_lineno(node)
            func_source = _get_source_slice(lines, node.lineno, func_end)
            entities.append(
                CodeEntity(
                    type="function",
                    name=node.name,
                    qualified_name=node.name,
                    file_path=file_path,
                    start_line=node.lineno,
                    end_line=func_end,
                    source=func_source,
                    docstring=ast.get_docstring(node),
                    decorators=_decorators(node),
                    visibility=_visibility(node.name),
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                )
            )

    return entities


# ---------------------------------------------------------------------------
# Python call extraction
# ---------------------------------------------------------------------------

_PY_BUILTINS: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "list",
        "dict",
        "tuple",
        "set",
        "bool",
        "type",
        "super",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
    }
)


def _extract_py_calls(entities: list[CodeEntity]) -> list[tuple[str, str, str]]:
    """Return ``(caller_qn, caller_fp, callee_name)`` triples for Python entities."""
    results: list[tuple[str, str, str]] = []
    for entity in entities:
        if entity.type not in ("function", "method"):
            continue
        try:
            tree = ast.parse(entity.source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                callee = func.id
            elif isinstance(func, ast.Attribute):
                callee = func.attr
            else:
                continue
            if callee in _PY_BUILTINS:
                continue
            results.append((entity.qualified_name, entity.file_path, callee))
    return results


# ---------------------------------------------------------------------------
# Python import resolution
# ---------------------------------------------------------------------------


def _resolve_py_import(
    import_str: str,
    _importer_path: str,  # unused — Python uses dotted module paths, not relative paths
    known_files: dict[str, str],
) -> str | None:
    """Map a dotted Python import string to a known in-repo file ID.

    Works regardless of whether the repo was ingested from the package root
    (paths like ``aquila_atlas/ingestion/parser.py``) or from inside the package
    (paths like ``ingestion/parser.py`` when the loader root was the package dir).
    """

    def _match(candidate: str) -> str | None:
        for file_path, file_id in known_files.items():
            if (
                file_path == candidate
                or candidate.endswith("/" + file_path)
                or file_path.endswith("/" + candidate)
            ):
                return file_id
        return None

    return _match(import_str.replace(".", "/") + ".py") or _match(
        import_str.replace(".", "/") + "/__init__.py"
    )


# ---------------------------------------------------------------------------
# Language plugin registration
# ---------------------------------------------------------------------------

from aquila_atlas.ingestion.language import LanguagePlugin, register  # noqa: E402

_PYTHON_PLUGIN = LanguagePlugin(
    name="Python",
    extensions=frozenset({".py"}),
    parse_file=lambda content, path: parse_python(content.decode("utf-8", errors="replace"), path),
    extract_calls=_extract_py_calls,
    resolve_import=_resolve_py_import,
)
register(_PYTHON_PLUGIN)
