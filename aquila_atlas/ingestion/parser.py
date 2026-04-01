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
    """Return all top-level import targets as dotted strings."""
    result: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result.append(f"{module}.{alias.name}" if module else alias.name)
    return tuple(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(file: RawFile) -> list[CodeEntity]:
    """Dispatch to the appropriate parser based on file extension."""
    suffix = Path(file.path).suffix.lower()
    if suffix == ".py":
        try:
            source = file.content.decode("utf-8")
        except UnicodeDecodeError:
            return []
        return parse_python(source, file.path)
    # Non-Python: single file-level entity
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
