"""Generic tree-sitter parser for multiple languages via tree-sitter-language-pack.

Supports: Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin, Swift, Lua, Bash, Scala, COBOL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

from aquila_atlas.ingestion.language import LanguagePlugin, register
from aquila_atlas.ingestion.metadata import CodeEntity, Visibility

logger = logging.getLogger("aquila.treesitter_parser")

# ---------------------------------------------------------------------------
# Language configuration
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


def _parse_generic(source_bytes: bytes, file_path: str, config: LangConfig) -> list[CodeEntity]:
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


# ---------------------------------------------------------------------------
# Language configurations
# ---------------------------------------------------------------------------

_JAVA = LangConfig(
    ts_name="java",
    extensions=frozenset({".java"}),
    function_types=frozenset({"method_declaration", "constructor_declaration"}),
    class_types=frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "annotation_type_declaration",
        }
    ),
    method_types=frozenset({"method_declaration", "constructor_declaration"}),
    import_types=frozenset({"import_declaration"}),
)

_GO = LangConfig(
    ts_name="go",
    extensions=frozenset({".go"}),
    function_types=frozenset({"function_declaration", "method_declaration"}),
    class_types=frozenset({"type_declaration"}),
    method_types=frozenset(),
    import_types=frozenset({"import_declaration"}),
)

_RUST = LangConfig(
    ts_name="rust",
    extensions=frozenset({".rs"}),
    function_types=frozenset({"function_item"}),
    class_types=frozenset({"struct_item", "enum_item", "trait_item", "impl_item"}),
    method_types=frozenset({"function_item"}),
    import_types=frozenset({"use_declaration"}),
)

_C = LangConfig(
    ts_name="c",
    extensions=frozenset({".c", ".h"}),
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"struct_specifier", "union_specifier", "enum_specifier"}),
    method_types=frozenset(),
    import_types=frozenset({"preproc_include"}),
    c_style_declarator=True,
)

_CPP = LangConfig(
    ts_name="cpp",
    extensions=frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h++"}),
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"class_specifier", "struct_specifier"}),
    method_types=frozenset({"function_definition"}),
    import_types=frozenset({"preproc_include"}),
    c_style_declarator=True,
)

_CSHARP = LangConfig(
    ts_name="c_sharp",
    extensions=frozenset({".cs"}),
    function_types=frozenset({"method_declaration", "constructor_declaration"}),
    class_types=frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "enum_declaration",
            "record_declaration",
        }
    ),
    method_types=frozenset({"method_declaration", "constructor_declaration"}),
    import_types=frozenset({"using_directive"}),
)

_RUBY = LangConfig(
    ts_name="ruby",
    extensions=frozenset({".rb"}),
    function_types=frozenset({"method", "singleton_method"}),
    class_types=frozenset({"class", "module"}),
    method_types=frozenset({"method", "singleton_method"}),
    import_types=frozenset(),
)

_PHP = LangConfig(
    ts_name="php",
    extensions=frozenset({".php"}),
    function_types=frozenset({"function_definition"}),
    class_types=frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "trait_declaration",
            "enum_declaration",
        }
    ),
    method_types=frozenset({"method_declaration"}),
    import_types=frozenset(
        {
            "require_expression",
            "include_expression",
            "require_once_expression",
            "include_once_expression",
        }
    ),
)

_KOTLIN = LangConfig(
    ts_name="kotlin",
    extensions=frozenset({".kt", ".kts"}),
    function_types=frozenset({"function_declaration"}),
    class_types=frozenset({"class_declaration", "object_declaration", "interface_declaration"}),
    method_types=frozenset({"function_declaration"}),
    import_types=frozenset({"import_header"}),
)

_SWIFT = LangConfig(
    ts_name="swift",
    extensions=frozenset({".swift"}),
    function_types=frozenset({"function_declaration"}),
    class_types=frozenset(
        {
            "class_declaration",
            "struct_declaration",
            "enum_declaration",
            "protocol_declaration",
            "extension_declaration",
        }
    ),
    method_types=frozenset({"function_declaration"}),
    import_types=frozenset({"import_declaration"}),
)

_LUA = LangConfig(
    ts_name="lua",
    extensions=frozenset({".lua"}),
    function_types=frozenset({"function_declaration", "local_function"}),
    class_types=frozenset(),
    method_types=frozenset(),
    import_types=frozenset(),
)

_BASH = LangConfig(
    ts_name="bash",
    extensions=frozenset({".sh", ".bash"}),
    function_types=frozenset({"function_definition"}),
    class_types=frozenset(),
    method_types=frozenset(),
    import_types=frozenset(),
)

_SCALA = LangConfig(
    ts_name="scala",
    extensions=frozenset({".scala"}),
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"class_definition", "object_definition", "trait_definition"}),
    method_types=frozenset({"function_definition"}),
    import_types=frozenset({"import_declaration"}),
)

# COBOL: paragraphs are function-like, sections group paragraphs (class-like),
# COPY statements are the import mechanism for copybooks.
_COBOL = LangConfig(
    ts_name="cobol",
    extensions=frozenset({".cob", ".cbl", ".cobol", ".cpy"}),
    function_types=frozenset({"paragraph"}),
    class_types=frozenset({"program_unit", "section"}),
    method_types=frozenset(),
    import_types=frozenset({"copy_statement"}),
)

_ALL_CONFIGS: list[LangConfig] = [
    _JAVA,
    _GO,
    _RUST,
    _C,
    _CPP,
    _CSHARP,
    _RUBY,
    _PHP,
    _KOTLIN,
    _SWIFT,
    _LUA,
    _BASH,
    _SCALA,
    _COBOL,
]

# ---------------------------------------------------------------------------
# C/C++ import resolver
# ---------------------------------------------------------------------------


def _resolve_c_include(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    """Resolve #include "relative/path.h" to a known in-repo file ID."""
    import posixpath  # noqa: PLC0415

    if not import_str or import_str.startswith("<"):
        return None
    stripped = import_str.strip("\"'")
    importer_dir = posixpath.dirname(importer_path)
    candidate = posixpath.normpath(posixpath.join(importer_dir, stripped))
    return known_files.get(candidate)


def _resolve_dotted_import(
    import_str: str, _importer_path: str, known_files: dict[str, str], exts: tuple[str, ...]
) -> str | None:
    """Resolve a dotted package import (Java/Kotlin/Scala/C#) to a known file.

    ``import com.example.MyClass`` → tries ``com/example/MyClass.java`` etc.
    Suffix-matches so ingestion root doesn't need to be the package root.

    Handles:
    - Regular imports: ``import com.example.MyClass``
    - Java static imports: ``import static com.example.Util.helper`` (strips "static ")
    - Kotlin/Scala aliases: ``import com.example.Foo as Bar`` (uses the original name)
    """
    clean = import_str.strip().rstrip(";").strip()
    if not clean:
        return None
    # Strip Java "static" keyword: "import static com.example.X" → "com.example.X"
    if clean.startswith("static "):
        clean = clean[7:].strip()
    # Strip alias suffix: "com.example.Foo as Bar" → "com.example.Foo"
    if " as " in clean:
        clean = clean.split(" as ")[0].strip()
    # Skip remaining spaces (unknown form) and wildcard imports
    if not clean or "*" in clean or "{" in clean or " " in clean:
        return None
    base = clean.replace(".", "/")
    for ext in exts:
        candidate = base + ext
        for file_path, file_id in known_files.items():
            fp = file_path.replace("\\", "/")
            if fp == candidate or fp.endswith("/" + candidate):
                return file_id
    return None


def _resolve_java_import(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    return _resolve_dotted_import(import_str, importer_path, known_files, (".java",))


def _resolve_kotlin_import(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    return _resolve_dotted_import(import_str, importer_path, known_files, (".kt", ".kts"))


def _resolve_scala_import(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    return _resolve_dotted_import(import_str, importer_path, known_files, (".scala",))


def _resolve_csharp_import(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    return _resolve_dotted_import(import_str, importer_path, known_files, (".cs",))


def _resolve_php_import(
    import_str: str, importer_path: str, known_files: dict[str, str]
) -> str | None:
    """Resolve PHP require/include string paths."""
    import posixpath  # noqa: PLC0415

    if not import_str:
        return None
    importer_dir = posixpath.dirname(importer_path)
    for trial in (import_str, import_str + ".php"):
        candidate = posixpath.normpath(posixpath.join(importer_dir, trial))
        if candidate in known_files:
            return known_files[candidate]
    return None


def _resolve_rust_import(
    import_str: str, _importer_path: str, known_files: dict[str, str]
) -> str | None:
    """Resolve ``use crate::module::submodule`` to a known ``.rs`` file."""
    clean = import_str.strip().rstrip(";")
    if clean.startswith("use "):
        clean = clean[4:]
    # Strip path qualifiers
    for prefix in ("crate::", "super::", "self::"):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
    # Drop type-alias suffix (e.g. ``Foo as Bar``)
    clean = clean.split(" as ")[0].strip()
    # Drop trailing type/item (last segment may be a type, try without it too)
    parts = clean.split("::")
    candidates_bases = [
        "/".join(parts),
        "/".join(parts[:-1]) if len(parts) > 1 else None,
    ]
    for base in candidates_bases:
        if not base:
            continue
        for candidate in (base + ".rs", base + "/mod.rs", "src/" + base + ".rs"):
            for file_path, file_id in known_files.items():
                fp = file_path.replace("\\", "/")
                if fp == candidate or fp.endswith("/" + candidate):
                    return file_id
    return None


def _resolve_go_import(
    import_str: str, _importer_path: str, known_files: dict[str, str]
) -> str | None:
    """Heuristic: match the last 1-3 segments of a Go module import path.

    ``github.com/user/repo/pkg/store`` → looks for files under ``pkg/store/``.
    """
    if not import_str:
        return None
    parts = import_str.strip("/").split("/")
    # Try progressively longer suffixes (most-specific first)
    for n in range(min(3, len(parts)), 0, -1):
        suffix = "/".join(parts[-n:])
        for file_path, file_id in known_files.items():
            fp = file_path.replace("\\", "/")
            if ("/" + suffix + "/") in fp or fp.startswith(suffix + "/"):
                return file_id
    return None


# Resolver dispatch: ts_name → resolve_import function
_RESOLVERS: dict[str, Any] = {
    "java": _resolve_java_import,
    "kotlin": _resolve_kotlin_import,
    "scala": _resolve_scala_import,
    "c_sharp": _resolve_csharp_import,
    "php": _resolve_php_import,
    "rust": _resolve_rust_import,
    "go": _resolve_go_import,
    "c": _resolve_c_include,
    "cpp": _resolve_c_include,
}


# ---------------------------------------------------------------------------
# Plugin factory and registration
# ---------------------------------------------------------------------------


def _make_plugin(config: LangConfig) -> LanguagePlugin:
    resolver = _RESOLVERS.get(config.ts_name)
    if resolver is not None:
        return LanguagePlugin(
            name=config.ts_name.replace("_", " ").title(),
            extensions=config.extensions,
            parse_file=lambda src, path, cfg=config: _parse_generic(src, path, cfg),
            resolve_import=resolver,
        )
    return LanguagePlugin(
        name=config.ts_name.replace("_", " ").title(),
        extensions=config.extensions,
        parse_file=lambda src, path, cfg=config: _parse_generic(src, path, cfg),
    )


for _cfg in _ALL_CONFIGS:
    register(_make_plugin(_cfg))
