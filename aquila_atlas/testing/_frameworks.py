"""Language → test framework mapping and output-path derivation."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FrameworkInfo:
    framework: str
    file_ext: str
    language_display: str
    is_stub: bool = False


# Maps lowercase language name (as stored in the graph) to framework info.
FRAMEWORK_MAP: dict[str, FrameworkInfo] = {
    "python": FrameworkInfo("pytest", ".py", "Python"),
    "typescript": FrameworkInfo("vitest", ".ts", "TypeScript"),
    "javascript": FrameworkInfo("vitest", ".js", "JavaScript"),
    "java": FrameworkInfo("junit5", ".java", "Java"),
    "go": FrameworkInfo("testing", ".go", "Go"),
    "rust": FrameworkInfo("builtin", ".rs", "Rust"),
    "c#": FrameworkInfo("xunit", ".cs", "C#"),
    "csharp": FrameworkInfo("xunit", ".cs", "C#"),
    "ruby": FrameworkInfo("rspec", ".rb", "Ruby"),
    "kotlin": FrameworkInfo("kotest", ".kt", "Kotlin"),
    "php": FrameworkInfo("phpunit", ".php", "PHP"),
    "swift": FrameworkInfo("xctest", ".swift", "Swift"),
    "scala": FrameworkInfo("scalatest", ".scala", "Scala"),
    "bash": FrameworkInfo("bats-core", ".bats", "Bash"),
    "shell": FrameworkInfo("bats-core", ".bats", "Bash"),
    "cobol": FrameworkInfo("stub", ".cbl", "COBOL", is_stub=True),
}

# Extension → language (for detection from file path)
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "c#",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".sc": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".cob": "cobol",
    ".cbl": "cobol",
    ".cobol": "cobol",
}


def detect_language(file_path: str) -> str | None:
    """Return lowercase language name for a file path, or None if unknown."""
    ext = pathlib.Path(file_path.replace("\\", "/")).suffix.lower()
    return _EXT_TO_LANG.get(ext)


def get_framework(language: str) -> FrameworkInfo | None:
    """Return FrameworkInfo for a language name (case-insensitive), or None."""
    return FRAMEWORK_MAP.get(language.lower())


def derive_output_path(source_path: str, language: str) -> str:
    """Derive the test output file path from a source file path.

    The naming convention follows each language's idiomatic layout:
    - Python  : tests/<source_dir>/test_<stem>.py
    - TS/JS   : src/__tests__/<stem>.test.<ext>
    - Java    : src/test/java/…/<Stem>Test.java  (src/main/java → src/test/java)
    - Go      : <same_dir>/<stem>_test.go
    - Rust    : tests/<stem>.rs
    - C#      : <stem>Tests.cs
    - Ruby    : spec/<stem>_spec.rb
    - Kotlin  : <stem>Test.kt
    - PHP     : tests/<Stem>Test.php
    - Swift   : <Stem>Tests.swift
    - Scala   : <Stem>Spec.scala
    - Bash    : test_<stem>.bats
    - COBOL   : tests/<stem>_stub.cbl
    """
    fw = get_framework(language)
    if fw is None:
        return f"tests/{source_path}"

    norm = source_path.replace("\\", "/")
    p = pathlib.PurePosixPath(norm)
    stem = p.stem
    parent = str(p.parent) if str(p.parent) != "." else ""
    cap_stem = stem[0].upper() + stem[1:] if stem else stem

    lang = language.lower()

    if lang == "python":
        prefix = f"{parent}/" if parent else ""
        return f"tests/{prefix}test_{stem}.py"

    if lang in ("typescript", "javascript"):
        ext = ".ts" if lang == "typescript" else ".js"
        return f"src/__tests__/{stem}.test{ext}"

    if lang == "java":
        # Map src/main/java → src/test/java
        test_parent = parent.replace("src/main/java", "src/test/java", 1)
        if test_parent == parent:
            test_parent = f"src/test/java/{parent}" if parent else "src/test/java"
        return f"{test_parent}/{cap_stem}Test.java"

    if lang == "go":
        prefix = f"{parent}/" if parent else ""
        return f"{prefix}{stem}_test.go"

    if lang == "rust":
        return f"tests/{stem}.rs"

    if lang in ("c#", "csharp"):
        return f"{cap_stem}Tests.cs"

    if lang == "ruby":
        prefix = f"{parent}/" if parent else ""
        return f"spec/{prefix}{stem}_spec.rb"

    if lang == "kotlin":
        return f"{cap_stem}Test.kt"

    if lang == "php":
        return f"tests/{cap_stem}Test.php"

    if lang == "swift":
        return f"{cap_stem}Tests.swift"

    if lang == "scala":
        return f"{cap_stem}Spec.scala"

    if lang in ("bash", "shell"):
        return f"test_{stem}.bats"

    if lang == "cobol":
        return f"tests/{stem}_stub.cbl"

    # Fallback
    return f"tests/{stem}_test{fw.file_ext}"
