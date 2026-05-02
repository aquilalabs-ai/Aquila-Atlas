"""Tests for testing/_frameworks.py — language detection, framework lookup, output paths."""

from __future__ import annotations

import pytest

from aquila_atlas.testing._frameworks import (
    FRAMEWORK_MAP,
    FrameworkInfo,
    derive_output_path,
    detect_language,
    get_framework,
)

# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_path, expected",
    [
        ("app.py", "python"),
        ("src/app.py", "python"),
        ("main.ts", "typescript"),
        ("component.tsx", "typescript"),
        ("index.js", "javascript"),
        ("App.jsx", "javascript"),
        ("util.mjs", "javascript"),
        ("Main.java", "java"),
        ("main.go", "go"),
        ("lib.rs", "rust"),
        ("Service.cs", "c#"),
        ("helper.rb", "ruby"),
        ("Main.kt", "kotlin"),
        ("main.kts", "kotlin"),
        ("Controller.php", "php"),
        ("ViewController.swift", "swift"),
        ("App.scala", "scala"),
        ("Main.sc", "scala"),
        ("run.sh", "bash"),
        ("test.bash", "bash"),
        ("program.cob", "cobol"),
        ("program.cbl", "cobol"),
        ("program.cobol", "cobol"),
        # Case insensitivity on extension
        ("App.PY", "python"),
        ("Main.JAVA", "java"),
        # Unknown extensions
        ("README.md", None),
        ("config.yaml", None),
        ("binary.exe", None),
        ("noext", None),
    ],
)
def test_detect_language(file_path: str, expected: str | None) -> None:
    assert detect_language(file_path) == expected


def test_detect_language_windows_path() -> None:
    assert detect_language("src\\module\\app.py") == "python"


# ---------------------------------------------------------------------------
# FRAMEWORK_MAP completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "language, framework",
    [
        ("python", "pytest"),
        ("typescript", "vitest"),
        ("javascript", "vitest"),
        ("java", "junit5"),
        ("go", "testing"),
        ("rust", "builtin"),
        ("c#", "xunit"),
        ("csharp", "xunit"),
        ("ruby", "rspec"),
        ("kotlin", "kotest"),
        ("php", "phpunit"),
        ("swift", "xctest"),
        ("scala", "scalatest"),
        ("bash", "bats-core"),
        ("shell", "bats-core"),
        ("cobol", "stub"),
    ],
)
def test_framework_map_entries(language: str, framework: str) -> None:
    assert language in FRAMEWORK_MAP
    assert FRAMEWORK_MAP[language].framework == framework


def test_cobol_is_stub() -> None:
    assert FRAMEWORK_MAP["cobol"].is_stub is True


def test_non_stub_languages_are_not_stubs() -> None:
    for lang, fw in FRAMEWORK_MAP.items():
        if lang != "cobol":
            assert fw.is_stub is False, f"{lang} should not be a stub"


def test_framework_info_is_frozen() -> None:
    fw = FrameworkInfo("pytest", ".py", "Python")
    with pytest.raises((AttributeError, TypeError)):
        fw.framework = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_framework
# ---------------------------------------------------------------------------


def test_get_framework_known() -> None:
    fw = get_framework("python")
    assert fw is not None
    assert fw.framework == "pytest"
    assert fw.file_ext == ".py"
    assert fw.language_display == "Python"


def test_get_framework_case_insensitive() -> None:
    assert get_framework("PYTHON") == get_framework("python")
    assert get_framework("TypeScript") == get_framework("typescript")


def test_get_framework_unknown() -> None:
    assert get_framework("brainfuck") is None


def test_get_framework_csharp_aliases_match() -> None:
    assert get_framework("c#") == get_framework("csharp")


# ---------------------------------------------------------------------------
# derive_output_path — all languages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_path, language, expected",
    [
        # Python
        ("app.py", "python", "tests/test_app.py"),
        ("src/module/app.py", "python", "tests/src/module/test_app.py"),
        # TypeScript
        ("src/service.ts", "typescript", "src/__tests__/service.test.ts"),
        ("component.tsx", "typescript", "src/__tests__/component.test.ts"),
        # JavaScript
        ("src/utils.js", "javascript", "src/__tests__/utils.test.js"),
        # Java — src/main/java rewrite
        (
            "src/main/java/com/example/Service.java",
            "java",
            "src/test/java/com/example/ServiceTest.java",
        ),
        # Java — non-standard path gets src/test/java prepended
        ("Service.java", "java", "src/test/java/ServiceTest.java"),
        # Go — same dir, _test suffix
        ("pkg/parser.go", "go", "pkg/parser_test.go"),
        ("main.go", "go", "main_test.go"),
        # Rust
        ("src/lib.rs", "rust", "tests/lib.rs"),
        # C#
        ("Services/UserService.cs", "c#", "UserServiceTests.cs"),
        ("handler.cs", "csharp", "HandlerTests.cs"),
        # Ruby
        ("lib/parser.rb", "ruby", "spec/lib/parser_spec.rb"),
        ("parser.rb", "ruby", "spec/parser_spec.rb"),
        # Kotlin
        ("src/Main.kt", "kotlin", "MainTest.kt"),
        # PHP
        ("src/Service.php", "php", "tests/ServiceTest.php"),
        # Swift
        ("Sources/Auth.swift", "swift", "AuthTests.swift"),
        # Scala
        ("src/Main.scala", "scala", "MainSpec.scala"),
        # Bash
        ("scripts/deploy.sh", "bash", "test_deploy.bats"),
        # COBOL
        ("program.cbl", "cobol", "tests/program_stub.cbl"),
        # Unknown language — fallback
        ("src/app.xyz", "brainfuck", "tests/src/app.xyz"),
    ],
)
def test_derive_output_path(source_path: str, language: str, expected: str) -> None:
    assert derive_output_path(source_path, language) == expected


def test_derive_output_path_windows_separators() -> None:
    # Windows paths should be normalized
    result = derive_output_path("src\\module\\app.py", "python")
    assert result == "tests/src/module/test_app.py"


def test_derive_output_path_java_no_main_java_prefix() -> None:
    # When path doesn't have src/main/java, it gets src/test/java/ prepended
    result = derive_output_path("com/example/Main.java", "java")
    assert result == "src/test/java/com/example/MainTest.java"
