"""Language configurations for the generic tree-sitter parser."""

from __future__ import annotations

from aquila_atlas.ingestion.parsers.treesitter._engine import LangConfig

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

ALL_CONFIGS: list[LangConfig] = [
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
]
