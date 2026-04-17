"""Tree-sitter language plugins — registration entry point.

Importing this package registers all supported tree-sitter languages
(Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin, Swift, Lua, Bash, Scala)
with the language plugin registry.
"""

from aquila_atlas.ingestion.language import LanguagePlugin, register
from aquila_atlas.ingestion.parsers.treesitter._configs import ALL_CONFIGS
from aquila_atlas.ingestion.parsers.treesitter._engine import LangConfig, parse_generic
from aquila_atlas.ingestion.parsers.treesitter._resolvers import RESOLVERS


def _make_plugin(config: LangConfig) -> LanguagePlugin:
    resolver = RESOLVERS.get(config.ts_name)
    if resolver is not None:
        return LanguagePlugin(
            name=config.ts_name.replace("_", " ").title(),
            extensions=config.extensions,
            parse_file=lambda src, path, cfg=config: parse_generic(src, path, cfg),  # type: ignore[misc]
            resolve_import=resolver,
        )
    return LanguagePlugin(
        name=config.ts_name.replace("_", " ").title(),
        extensions=config.extensions,
        parse_file=lambda src, path, cfg=config: parse_generic(src, path, cfg),  # type: ignore[misc]
    )


for _cfg in ALL_CONFIGS:
    register(_make_plugin(_cfg))

__all__ = ["LangConfig", "parse_generic"]
