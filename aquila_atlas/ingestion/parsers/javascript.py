"""Tree-sitter based parser for JavaScript and TypeScript source files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from aquila_atlas.ingestion.metadata import CodeEntity, Visibility

# ---------------------------------------------------------------------------
# Language objects (module-level singletons — initialised once)
# ---------------------------------------------------------------------------

_JS_LANGUAGE: Language = Language(tsjs.language())
_TS_LANGUAGE: Language = Language(tsts.language_typescript())
_TSX_LANGUAGE: Language = Language(tsts.language_tsx())

_SUFFIX_TO_LANG: dict[str, Language] = {
    ".js": _JS_LANGUAGE,
    ".jsx": _JS_LANGUAGE,
    ".ts": _TS_LANGUAGE,
    ".tsx": _TSX_LANGUAGE,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser(suffix: str) -> Parser:
    lang = _SUFFIX_TO_LANG.get(suffix, _JS_LANGUAGE)
    return Parser(lang)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _source_slice(lines: list[str], start: int, end: int) -> str:
    """Return source lines [start, end] (1-based, inclusive)."""
    return "".join(lines[start - 1 : end])


def _visibility(name: str) -> Visibility:
    if name.startswith("#") or name.startswith("_"):
        return "private"
    return "public"


def _is_async(node: Node) -> bool:
    """Return True if any direct child has type 'async'."""
    return any(child.type == "async" for child in node.children)


def _extract_name(node: Node, source: bytes) -> str | None:
    """Return the text of the 'name' field child, or None."""
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source)
    return None


def _jsdoc(node: Node, source: bytes) -> str | None:
    """Return the JSDoc comment immediately preceding *node*, or None."""
    prev = node.prev_sibling
    # Skip over whitespace/newline-only comment nodes
    while (
        prev is not None
        and prev.type in {"comment"}
        and not _node_text(prev, source).startswith("/*")
    ):
        prev = prev.prev_sibling
    if prev is not None and prev.type == "comment":
        text = _node_text(prev, source).strip()
        if text.startswith("/**"):
            # Strip /** ... */ delimiters and leading * on each line
            inner = text[3:-2]  # remove /** and */
            lines = [line.lstrip().lstrip("*").rstrip() for line in inner.splitlines()]
            return "\n".join(line for line in lines if line).strip() or None
    return None


def _extract_imports(root: Node, source: bytes) -> tuple[str, ...]:
    """Collect module paths from top-level import statements."""
    seen: set[str] = set()
    result: list[str] = []
    for child in root.children:
        if child.type not in {"import_statement", "import_declaration"}:
            continue
        # The string/string_fragment child holds the module path
        for sub in child.children:
            if sub.type == "string":
                raw = _node_text(sub, source).strip("'\"` ")
                if raw and raw not in seen:
                    seen.add(raw)
                    result.append(raw)
    return tuple(result)


# ---------------------------------------------------------------------------
# Entity extractors
# ---------------------------------------------------------------------------


def _extract_class(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
) -> list[CodeEntity]:
    """Extract a class declaration and its methods."""
    entities: list[CodeEntity] = []
    name = _extract_name(node, source)
    if name is None:
        return []

    start = node.start_point[0] + 1
    end = node.end_point[0] + 1

    entities.append(
        CodeEntity(
            type="class",
            name=name,
            qualified_name=name,
            file_path=file_path,
            start_line=start,
            end_line=end,
            source=_source_slice(lines, start, end),
            docstring=_jsdoc(node, source),
            visibility=_visibility(name),
        )
    )

    # Methods inside the class body
    body = node.child_by_field_name("body")
    if body is None:
        return entities

    for child in body.children:
        if child.type not in {"method_definition", "public_field_definition"}:
            continue
        if child.type == "public_field_definition":
            # Only process if the value is a function/arrow
            val = child.child_by_field_name("value")
            if val is None or val.type not in {"function", "arrow_function"}:
                continue

        method_name = _extract_name(child, source)
        if method_name is None:
            continue

        m_start = child.start_point[0] + 1
        m_end = child.end_point[0] + 1

        entities.append(
            CodeEntity(
                type="method",
                name=method_name,
                qualified_name=f"{name}.{method_name}",
                file_path=file_path,
                start_line=m_start,
                end_line=m_end,
                source=_source_slice(lines, m_start, m_end),
                docstring=_jsdoc(child, source),
                parent=name,
                visibility=_visibility(method_name),
                is_async=_is_async(child),
            )
        )

    return entities


def _extract_function(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
) -> CodeEntity | None:
    """Extract a top-level function declaration."""
    name = _extract_name(node, source)
    if name is None:
        return None

    start = node.start_point[0] + 1
    end = node.end_point[0] + 1

    return CodeEntity(
        type="function",
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        source=_source_slice(lines, start, end),
        docstring=_jsdoc(node, source),
        visibility=_visibility(name),
        is_async=_is_async(node),
    )


def _extract_arrow_var(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
) -> list[CodeEntity]:
    """Extract top-level arrow / function expressions stored in variables.

    Handles patterns like:
      const foo = () => { … }
      export const bar = async function() { … }
    """
    entities: list[CodeEntity] = []
    # node is lexical_declaration or variable_declaration
    for decl in node.children:
        if decl.type != "variable_declarator":
            continue
        value = decl.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function"}:
            continue
        name_node = decl.child_by_field_name("name")
        if name_node is None:
            continue
        name = _node_text(name_node, source)

        start = node.start_point[0] + 1
        end = node.end_point[0] + 1

        entities.append(
            CodeEntity(
                type="function",
                name=name,
                qualified_name=name,
                file_path=file_path,
                start_line=start,
                end_line=end,
                source=_source_slice(lines, start, end),
                docstring=_jsdoc(node, source),
                visibility=_visibility(name),
                is_async=_is_async(value),
            )
        )
    return entities


def _extract_interface(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
) -> CodeEntity | None:
    """Extract a TypeScript interface declaration."""
    name = _extract_name(node, source)
    if name is None:
        return None

    start = node.start_point[0] + 1
    end = node.end_point[0] + 1

    return CodeEntity(
        type="interface",
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        source=_source_slice(lines, start, end),
        docstring=_jsdoc(node, source),
        visibility=_visibility(name),
    )


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

_FUNCTION_TYPES = {"function_declaration", "generator_function_declaration"}
_VAR_TYPES = {"lexical_declaration", "variable_declaration"}
_CLASS_TYPES = {"class_declaration"}


def _process_node(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
    entities: list[CodeEntity],
) -> None:
    """Dispatch a top-level (or export-unwrapped) node to the right extractor."""
    t = node.type

    if t in _CLASS_TYPES:
        entities.extend(_extract_class(node, source, lines, file_path))

    elif t in _FUNCTION_TYPES:
        entity = _extract_function(node, source, lines, file_path)
        if entity is not None:
            entities.append(entity)

    elif t in _VAR_TYPES:
        entities.extend(_extract_arrow_var(node, source, lines, file_path))

    elif t == "interface_declaration":
        entity = _extract_interface(node, source, lines, file_path)
        if entity is not None:
            entities.append(entity)

    elif t == "export_statement":
        # Unwrap: export default / export const / export class / export function
        for child in node.children:
            if child.type not in {
                "default",
                "export",
                "identifier",
                ";",
                "string",
                "comment",
            }:
                _process_node(child, source, lines, file_path, entities)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_js_ts(source_bytes: bytes, file_path: str) -> list[CodeEntity]:
    """Parse a JS/TS/JSX/TSX file and return all code entities."""
    suffix = Path(file_path).suffix.lower()
    parser = _make_parser(suffix)

    try:
        source_str = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return []

    tree = parser.parse(source_bytes)
    root = tree.root_node

    lines = [line + "\n" for line in source_str.splitlines()]
    if source_str and not source_str.endswith("\n") and lines:
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
            source=source_str,
            imports=_extract_imports(root, source_bytes),
        )
    ]

    for child in root.children:
        _process_node(child, source_bytes, lines, file_path, entities)

    return entities


# ---------------------------------------------------------------------------
# Call extraction (used by graph.py)
# ---------------------------------------------------------------------------

_JS_TS_SUFFIXES: frozenset[str] = frozenset({".js", ".jsx", ".ts", ".tsx"})


def _iter_call_expressions(node: Node) -> Iterator[Node]:
    """Yield every call_expression node in the subtree."""
    if node.type == "call_expression":
        yield node
    for child in node.children:
        yield from _iter_call_expressions(child)


def extract_js_ts_calls(
    entities: list[CodeEntity],
) -> list[tuple[str, str, str]]:
    """Return ``(caller_qualified_name, caller_file_path, callee_name)`` triples.

    Mirrors the Python ``extract_calls()`` in ``graph.py`` but uses tree-sitter
    to walk ``call_expression`` nodes inside each JS/TS function or method body.
    Only simple names and property accesses are extracted (e.g. ``foo()`` → ``foo``,
    ``obj.bar()`` → ``bar``).  Resolution against known entities happens in the
    graph ingest pipeline.
    """
    results: list[tuple[str, str, str]] = []

    for entity in entities:
        if entity.type not in ("function", "method"):
            continue
        suffix = Path(entity.file_path).suffix.lower()
        if suffix not in _JS_TS_SUFFIXES:
            continue

        parser = _make_parser(suffix)
        source_bytes = entity.source.encode("utf-8")
        tree = parser.parse(source_bytes)

        seen: set[str] = set()
        for call_node in _iter_call_expressions(tree.root_node):
            fn_node = call_node.child_by_field_name("function")
            if fn_node is None:
                continue
            if fn_node.type == "identifier":
                callee = _node_text(fn_node, source_bytes)
            elif fn_node.type == "member_expression":
                prop = fn_node.child_by_field_name("property")
                callee = _node_text(prop, source_bytes) if prop is not None else ""
            else:
                continue
            if callee and callee not in seen:
                seen.add(callee)
                results.append((entity.qualified_name, entity.file_path, callee))

    return results


# ---------------------------------------------------------------------------
# JS/TS import resolution
# ---------------------------------------------------------------------------


def _resolve_ts_import(
    import_str: str,
    importer_file_path: str,
    known_files: dict[str, str],
) -> str | None:
    """Resolve a JS/TS relative import path to a known in-repo file ID.

    Only relative imports (starting with ``.`` or ``..``) can be resolved
    within the repo.  Bare specifiers (``react``, ``axios``) and path aliases
    (``@/…``) are external and return ``None``.

    Resolution order for ``./foo`` imported from ``src/pages/Home.tsx``:
      1. ``src/pages/foo``            — already has extension
      2. ``src/pages/foo.ts``
      3. ``src/pages/foo.tsx``
      4. ``src/pages/foo.js``
      5. ``src/pages/foo.jsx``
      6. ``src/pages/foo/index.ts``   — directory import
      … remaining index variants.
    """
    import posixpath  # noqa: PLC0415

    if not import_str.startswith("."):
        return None  # external package or path alias

    importer_dir = posixpath.dirname(importer_file_path)
    base = posixpath.normpath(posixpath.join(importer_dir, import_str))

    _EXTS = (".ts", ".tsx", ".js", ".jsx")
    candidates: list[str] = [base]
    candidates += [base + ext for ext in _EXTS]
    candidates += [base + "/index" + ext for ext in _EXTS]

    for candidate in candidates:
        if candidate in known_files:
            return known_files[candidate]
    return None


# ---------------------------------------------------------------------------
# Language plugin registration
# ---------------------------------------------------------------------------

from aquila_atlas.ingestion.language import LanguagePlugin, register  # noqa: E402

_JS_TS_PLUGIN = LanguagePlugin(
    name="JavaScript/TypeScript",
    extensions=frozenset({".js", ".jsx", ".ts", ".tsx"}),
    parse_file=parse_js_ts,
    extract_calls=extract_js_ts_calls,
    resolve_import=_resolve_ts_import,
)
register(_JS_TS_PLUGIN)