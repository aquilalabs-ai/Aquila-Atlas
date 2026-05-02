"""Tests for testing/_validator.py — syntax validation dispatch and code-fence stripper."""

from __future__ import annotations

from aquila_atlas.testing._validator import _strip_code_fence, validate

# ---------------------------------------------------------------------------
# validate() — Python (uses ast.parse; no external tool needed)
# ---------------------------------------------------------------------------


def test_validate_python_valid() -> None:
    code = "def add(a, b):\n    return a + b\n"
    ok, error = validate("tests/test_add.py", code)
    assert ok is True
    assert error is None


def test_validate_python_invalid() -> None:
    code = "def broken(\n    return 1\n"
    ok, error = validate("tests/test_broken.py", code)
    assert ok is False
    assert error is not None
    assert "SyntaxError" in error


def test_validate_python_empty_file() -> None:
    ok, error = validate("tests/test_empty.py", "")
    assert ok is True
    assert error is None


def test_validate_python_multiline_valid() -> None:
    code = "import pytest\n\ndef test_foo():\n    assert 1 + 1 == 2\n"
    ok, error = validate("tests/test_foo.py", code)
    assert ok is True


def test_validate_python_reports_line_number() -> None:
    code = "x = (\n    1 +\n"  # unclosed paren
    ok, error = validate("tests/test_x.py", code)
    assert ok is False
    assert error is not None


# ---------------------------------------------------------------------------
# validate() — skip logic
# ---------------------------------------------------------------------------


def test_validate_bats_is_skipped() -> None:
    # .bats files use @test syntax that bash -n cannot parse; must be syntax-only
    ok, error = validate("test_deploy.bats", "@test 'runs ok' { true; }")
    assert ok is None
    assert error is None


def test_validate_csharp_is_skipped() -> None:
    ok, error = validate("UserTests.cs", "class Foo {}")
    assert ok is None
    assert error is None


def test_validate_kotlin_is_skipped() -> None:
    ok, error = validate("MainTest.kt", "fun main() {}")
    assert ok is None
    assert error is None


def test_validate_swift_is_skipped() -> None:
    ok, error = validate("AuthTests.swift", "import XCTest")
    assert ok is None
    assert error is None


def test_validate_scala_is_skipped() -> None:
    ok, error = validate("MainSpec.scala", "object Spec extends AnyFlatSpec {}")
    assert ok is None
    assert error is None


def test_validate_cobol_is_skipped() -> None:
    ok, error = validate("tests/program_stub.cbl", "IDENTIFICATION DIVISION.")
    assert ok is None
    assert error is None


def test_validate_unknown_extension_is_skipped() -> None:
    ok, error = validate("tests/something.xyz", "content")
    assert ok is None
    assert error is None


# ---------------------------------------------------------------------------
# _strip_code_fence
# ---------------------------------------------------------------------------


def test_strip_fence_python_alias() -> None:
    text = "```python\ndef test(): pass\n```"
    result = _strip_code_fence(text, "python")
    assert result == "def test(): pass"


def test_strip_fence_py_alias() -> None:
    text = "```py\nx = 1\n```"
    result = _strip_code_fence(text, "python")
    assert result == "x = 1"


def test_strip_fence_typescript_ts_alias() -> None:
    text = "```ts\nconst x = 1;\n```"
    result = _strip_code_fence(text, "typescript")
    assert result == "const x = 1;"


def test_strip_fence_tsx_alias() -> None:
    text = "```tsx\nconst x = 1;\n```"
    result = _strip_code_fence(text, "typescript")
    assert result == "const x = 1;"


def test_strip_fence_go_golang_alias() -> None:
    text = "```golang\npackage main\n```"
    result = _strip_code_fence(text, "go")
    assert result == "package main"


def test_strip_fence_rust_rs_alias() -> None:
    text = "```rs\nfn main() {}\n```"
    result = _strip_code_fence(text, "rust")
    assert result == "fn main() {}"


def test_strip_fence_csharp_aliases() -> None:
    for alias in ("csharp", "cs", "c#"):
        text = f"```{alias}\nclass Foo {{}}\n```"
        result = _strip_code_fence(text, "c#")
        assert result == "class Foo {}"


def test_strip_fence_fallback_any_tag() -> None:
    # Generic fence with an unknown but alphanumeric tag
    text = "```somethingelse\ncontent here\n```"
    result = _strip_code_fence(text, "python")
    assert result == "content here"


def test_strip_fence_no_fence_returns_stripped_text() -> None:
    text = "  def test(): pass  "
    result = _strip_code_fence(text, "python")
    assert result == "def test(): pass"


def test_strip_fence_case_insensitive_match() -> None:
    text = "```PYTHON\ndef f(): pass\n```"
    result = _strip_code_fence(text, "python")
    assert result == "def f(): pass"


def test_strip_fence_bash_aliases() -> None:
    for alias in ("bash", "sh", "shell"):
        text = f"```{alias}\necho hello\n```"
        result = _strip_code_fence(text, "bash")
        assert result == "echo hello"


def test_strip_fence_cobol_alias() -> None:
    text = "```cbl\nIDENTIFICATION DIVISION.\n```"
    result = _strip_code_fence(text, "cobol")
    assert result == "IDENTIFICATION DIVISION."


def test_strip_fence_java() -> None:
    text = "```java\npublic class Test {}\n```"
    result = _strip_code_fence(text, "java")
    assert result == "public class Test {}"


def test_strip_fence_ruby_rb_alias() -> None:
    text = "```rb\ndescribe 'foo' do; end\n```"
    result = _strip_code_fence(text, "ruby")
    assert result == "describe 'foo' do; end"
