"""Language plugin registry.

Each language module self-registers a :class:`LanguagePlugin` instance at import
time by calling :func:`register`.  Callers retrieve the right plugin for a file
extension with :func:`get_plugin` — no ``if/elif`` chains needed anywhere else.

Adding a new language
---------------------
1. Create ``aquila_atlas/ingestion/<lang>_parser.py`` that implements and
   registers a ``LanguagePlugin``.
2. Add one line to :data:`_LAZY_MODULES` here, mapping every relevant extension
   to that module path.  That is the *only* file outside the new module that
   needs to change.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.ingestion.metadata import CodeEntity

# ---------------------------------------------------------------------------
# Default no-op callables (used as dataclass field defaults)
# ---------------------------------------------------------------------------


def _no_calls(entities: list[CodeEntity]) -> list[tuple[str, str, str]]:
    return []


def _no_resolve(import_str: str, importer_path: str, known_files: dict[str, str]) -> str | None:
    return None


# ---------------------------------------------------------------------------
# Plugin dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguagePlugin:
    """All language-specific analysis logic for one language (one or more extensions).

    Fields
    ------
    name
        Human-readable language name (e.g. ``"Python"``).
    extensions
        Set of lowercase file extensions handled by this plugin (e.g. ``{".py"}``).
    parse_file
        ``(source_bytes, file_path) → list[CodeEntity]`` — full entity extraction.
    extract_calls
        ``(entities) → [(caller_qn, caller_fp, callee_name), ...]`` — static call
        analysis.  Defaults to returning no calls.
    resolve_import
        ``(import_str, importer_file_path, known_files) → file_id | None`` — map
        a single import string to a known in-repo file ID.  Defaults to always
        returning ``None`` (unresolvable).
    """

    name: str
    extensions: frozenset[str]
    parse_file: Callable[[bytes, str], list[CodeEntity]]
    extract_calls: Callable[[list[CodeEntity]], list[tuple[str, str, str]]] = field(
        default=_no_calls
    )
    resolve_import: Callable[[str, str, dict[str, str]], str | None] = field(default=_no_resolve)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, LanguagePlugin] = {}

# Maps file extension → the module whose import side-effect registers its plugin.
# Add ONE LINE here when integrating a new language — nothing else changes.
_LAZY_MODULES: dict[str, str] = {
    ".py": "aquila_atlas.ingestion.parser",
    ".js": "aquila_atlas.ingestion.ts_parser",
    ".jsx": "aquila_atlas.ingestion.ts_parser",
    ".ts": "aquila_atlas.ingestion.ts_parser",
    ".tsx": "aquila_atlas.ingestion.ts_parser",
    # Java
    ".java": "aquila_atlas.ingestion.treesitter_parser",
    # Go
    ".go": "aquila_atlas.ingestion.treesitter_parser",
    # Rust
    ".rs": "aquila_atlas.ingestion.treesitter_parser",
    # C
    ".c": "aquila_atlas.ingestion.treesitter_parser",
    ".h": "aquila_atlas.ingestion.treesitter_parser",
    # C++
    ".cpp": "aquila_atlas.ingestion.treesitter_parser",
    ".cc": "aquila_atlas.ingestion.treesitter_parser",
    ".cxx": "aquila_atlas.ingestion.treesitter_parser",
    ".hpp": "aquila_atlas.ingestion.treesitter_parser",
    ".hh": "aquila_atlas.ingestion.treesitter_parser",
    # C#
    ".cs": "aquila_atlas.ingestion.treesitter_parser",
    # Ruby
    ".rb": "aquila_atlas.ingestion.treesitter_parser",
    # PHP
    ".php": "aquila_atlas.ingestion.treesitter_parser",
    # Kotlin
    ".kt": "aquila_atlas.ingestion.treesitter_parser",
    ".kts": "aquila_atlas.ingestion.treesitter_parser",
    # Swift
    ".swift": "aquila_atlas.ingestion.treesitter_parser",
    # Lua
    ".lua": "aquila_atlas.ingestion.treesitter_parser",
    # Bash
    ".sh": "aquila_atlas.ingestion.treesitter_parser",
    ".bash": "aquila_atlas.ingestion.treesitter_parser",
    # Scala
    ".scala": "aquila_atlas.ingestion.treesitter_parser",
    # COBOL
    ".cob": "aquila_atlas.ingestion.cobol_parser",
    ".cbl": "aquila_atlas.ingestion.cobol_parser",
    ".cobol": "aquila_atlas.ingestion.cobol_parser",
    ".cpy": "aquila_atlas.ingestion.cobol_parser",
}


def register(plugin: LanguagePlugin) -> None:
    """Register *plugin* for all its declared extensions."""
    for ext in plugin.extensions:
        _REGISTRY[ext] = plugin


def get_plugin(suffix: str) -> LanguagePlugin | None:
    """Return the plugin for *suffix* (e.g. ``'.py'``), or ``None``.

    On first access for an unregistered extension the corresponding module is
    imported (triggering its ``register()`` call) before the lookup is retried.
    """
    suffix = suffix.lower()
    if suffix not in _REGISTRY:
        module = _LAZY_MODULES.get(suffix)
        if module:
            importlib.import_module(module)
    return _REGISTRY.get(suffix)
