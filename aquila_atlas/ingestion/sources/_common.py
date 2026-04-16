"""Shared primitives for source loaders — filter rules, RawFile, and SourceLoader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from aquila_atlas.ingestion.metadata import SourceMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".lua": "Lua",
    ".h": "C",
    ".hpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hh": "C++",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}

# Paths / names to ignore during traversal
_IGNORE_NAMES: frozenset[str] = frozenset(
    {
        # Dependency directories
        "node_modules",
        "vendor",  # Go, PHP, Ruby
        "bower_components",
        # Python artifacts
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        # Build / dist output
        "dist",
        "build",
        "out",
        "target",  # Rust, Java/Maven
        "bin",
        "obj",  # .NET
        ".next",  # Next.js
        ".nuxt",  # Nuxt.js
        ".svelte-kit",  # SvelteKit
        ".output",  # Nitro / Nuxt output
        # Coverage & reports
        "coverage",
        "htmlcov",
        ".nyc_output",
        # Tool caches
        ".cache",
        ".parcel-cache",
        ".turbo",
        ".gradle",
        # VCS & IDE
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
    }
)

_IGNORE_SUFFIXES: frozenset[str] = frozenset(
    {
        # Compiled / binary
        ".pyc",
        ".pyo",
        ".class",  # Java bytecode
        ".o",
        ".a",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        # Minified assets (no value for code analysis)
        ".min.js",
        ".min.css",
        # Source maps
        ".map",
        # Lock files
        ".lock",
    }
)


def _should_ignore(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in _IGNORE_NAMES:
            return True
    # Check full suffix chain for compound extensions like .min.js
    name = Path(path).name
    return any(name.endswith(suffix) for suffix in _IGNORE_SUFFIXES)


def detect_languages(files: list[RawFile]) -> dict[str, int]:
    """Return a mapping of language name to total byte count across *files*."""
    counts: dict[str, int] = {}
    for f in files:
        suffix = Path(f.path).suffix.lower()
        lang = EXT_TO_LANG.get(suffix)
        if lang:
            counts[lang] = counts.get(lang, 0) + len(f.content)
    return counts


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawFile:
    """A single file as loaded from any source."""

    path: str  # relative path within the project (always forward-slash)
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SourceLoader(Protocol):
    """Common interface every source loader must implement."""

    def load(self) -> Iterator[RawFile]:
        """Yield all files from the source."""
        ...

    def label(self) -> str:
        """Human-readable identifier used in logs and metadata."""
        ...

    def metadata(self) -> SourceMetadata:
        """Return high-level metadata about this source."""
        ...