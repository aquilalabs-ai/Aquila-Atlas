"""Generic tree-sitter parsing engine shared across all tree-sitter languages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

from aquila_atlas.ingestion.metadata import CodeEntity, Visibility

logger = logging.getLogger("aquila.treesitter_parser")

# ---------------------------------------------------------------------------
# Language configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class LangConfig:
    ts_name: str
    extensions: frozenset[str]
    function_types: frozenset[str]
    class_types: frozenset[str]
    method_types: frozenset[str]
    import_types: frozenset[str]
    c_style_declarator: bool = False


# ---------------------------------------------------------------------------
# Parser cache — lazy-load once per language
# ---------------------------------------------------------------------------

_PARSER_CACHE: dict[str, Any] = {}


def _get_parser(ts_name: str) -> Any:
    if ts_name not in _PARSER_CACHE:
        from tree_sitter_language_pack import get_parser  # noqa: PLC0415

        _PARSER_CACHE[ts_name] = get_parser(ts_name)
    return _PARSER_CACHE[ts_name]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _source_slice(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def _visibility(name: str) -> Visibility:
    if name.startswith("_"):
        return "private"
    return "public"


def _extract_name(node: Node, source: bytes, c_style: bool = False) -> str | None:
    # 1. Standard name field
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source)

    # 2. Rust impl_item: use "type" field
    if node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node is not None:
            return _node_text(type_node, source)

    # 3. Go type_declaration: descend into type_spec → name
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                spec_name = child.child_by_field_name("name")
                if spec_name is not None:
                    return _node_text(spec_name, source)

    # 4. C/C++ declarator chain
    if c_style:
        decl = node.child_by_field_name("declarator")
        depth = 0
        while decl is not None and depth < 6:
            if decl.type == "identifier":
                return _node_text(decl, source)
            # qualified_identifier or destructor_name may expose a "name" field
            inner = decl.child_by_field_name("name")
            if inner is not None:
                return _node_text(inner, source)
            decl = decl.child_by_field_name("declarator")
            depth += 1

    # 5. Fallback: first identifier or type_identifier child
    for child in node.children:
        if child.type in {"identifier", "type_identifier"}:
            return _node_text(child, source)

    return None


_STRING_TYPES: frozenset[str] = frozenset(
    {
        "string_literal",
        "interpreted_string_literal",
        "string",
        "raw_string_literal",
        "system_lib_string",
    }
)


def _collect_string_children(node: Node, source: bytes) -> list[str]:
    """BFS collecting ALL string literal nodes; strips quote delimiters.

    Used instead of a first-match search so that Go grouped imports
    (``import ( "fmt"\\n "os" )``) yield every path, not just the first.
    """
    found: list[str] = []
    queue = list(node.children)
    while queue:
        child = queue.pop(0)
        if child.type in _STRING_TYPES:
            raw = _node_text(child, source).strip("\"'<>`")
            if raw:
                found.append(raw)
        else:
            queue.extend(child.children)
    return found


def _extract_imports(root: Node, source: bytes, import_types: frozenset[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for child in root.children:
        if child.type not in import_types:
            continue
        # Collect all string literals inside the import node first (handles
        # Go grouped imports, C/C++ #include, PHP require strings, etc.)
        strings = _collect_string_children(child, source)
        if strings:
            for s in strings:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
        else:
            # Fallback: full node text with keyword/semicolon stripping
            val = _node_text(child, source).strip()
            for prefix in ("import ", "using ", "use ", "#include "):
                if val.startswith(prefix):
                    val = val[len(prefix) :]
                    break
            val = val.rstrip(";").strip()
            if val and val not in seen:
                seen.add(val)
                result.append(val)
    return tuple(result)


def _find_methods_in_class(class_node: Node, method_types: frozenset[str]) -> list[Node]:
    """Walk 2 levels deep collecting nodes whose type is in method_types."""
    found: list[Node] = []
    for child in class_node.children:
        if child.type in method_types:
            found.append(child)
        for grandchild in child.children:
            if grandchild.type in method_types:
                found.append(grandchild)
    return found


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def _process_top_level(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
    config: LangConfig,
    entities: list[CodeEntity],
) -> None:
    if node.type in config.class_types:
        name = _extract_name(node, source, c_style=config.c_style_declarator)
        if name is None:
            return

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
                visibility=_visibility(name),
            )
        )

        if config.method_types:
            for method_node in _find_methods_in_class(node, config.method_types):
                m_name = _extract_name(method_node, source, c_style=config.c_style_declarator)
                if m_name is None:
                    continue
                m_start = method_node.start_point[0] + 1
                m_end = method_node.end_point[0] + 1
                entities.append(
                    CodeEntity(
                        type="method",
                        name=m_name,
                        qualified_name=f"{name}.{m_name}",
                        file_path=file_path,
                        start_line=m_start,
                        end_line=m_end,
                        source=_source_slice(lines, m_start, m_end),
                        parent=name,
                        visibility=_visibility(m_name),
                    )
                )

    elif node.type in config.function_types:
        name = _extract_name(node, source, c_style=config.c_style_declarator)
        if name is None:
            return

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
                visibility=_visibility(name),
            )
        )


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def parse_generic(source_bytes: bytes, file_path: str, config: LangConfig) -> list[CodeEntity]:
    try:
        source_str = source_bytes.decode("utf-8", errors="replace")
    except Exception:
        source_str = ""

    lines = [line + "\n" for line in source_str.splitlines()]
    if source_str and not source_str.endswith("\n") and lines:
        lines[-1] = lines[-1].rstrip("\n")
    total_lines = len(lines) if lines else 1
    stem = Path(file_path).stem

    file_entity = CodeEntity(
        type="file",
        name=stem,
        qualified_name=file_path,
        file_path=file_path,
        start_line=1,
        end_line=total_lines,
        source=source_str,
    )

    try:
        parser = _get_parser(config.ts_name)
        tree = parser.parse(source_bytes)
        root = tree.root_node

        imports = _extract_imports(root, source_bytes, config.import_types)
        # Rebuild file entity with imports now that we have them
        file_entity = CodeEntity(
            type="file",
            name=stem,
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=total_lines,
            source=source_str,
            imports=imports,
        )

        entities: list[CodeEntity] = [file_entity]
        for child in root.children:
            _process_top_level(child, source_bytes, lines, file_path, config, entities)

        return entities

    except Exception:
        logger.warning("tree-sitter parse failed for %s", file_path, exc_info=True)
        return [file_entity]