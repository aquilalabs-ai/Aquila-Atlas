"""Import resolver functions for each tree-sitter language."""

from __future__ import annotations

from typing import Any


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
RESOLVERS: dict[str, Any] = {
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
