"""Tests for testing/_zip.py — header builder, coverage/mock detection, README, ZIP assembly."""

from __future__ import annotations

import io
import zipfile

from aquila_atlas.testing._zip import (
    _build_header,
    _build_readme,
    _detect_coverage,
    _detect_mocks,
    build_test_zip,
)

# ---------------------------------------------------------------------------
# _detect_coverage
# ---------------------------------------------------------------------------


def test_detect_coverage_python() -> None:
    code = (
        "def test_add():\n    assert add(1, 2) == 3\n\n"
        "def test_subtract():\n    assert sub(3, 1) == 2\n"
    )
    result = _detect_coverage(code, "python")
    assert "add()" in result
    assert "subtract()" in result


def test_detect_coverage_python_strips_test_prefix() -> None:
    code = "def test_my_function():\n    pass\n"
    result = _detect_coverage(code, "python")
    assert "my_function()" in result


def test_detect_coverage_python_max_6() -> None:
    code = "\n".join(f"def test_fn{i}():\n    pass" for i in range(10))
    result = _detect_coverage(code, "python")
    assert len(result) <= 6


def test_detect_coverage_javascript() -> None:
    code = "it('parses input correctly', () => {});\ntest('handles error', () => {});"
    result = _detect_coverage(code, "javascript")
    assert any("parses input" in r for r in result)
    assert any("handles error" in r for r in result)


def test_detect_coverage_typescript() -> None:
    code = "it('renders the component', () => {});"
    result = _detect_coverage(code, "typescript")
    assert any("renders the component" in r for r in result)


def test_detect_coverage_java() -> None:
    code = "void testAddNumbers() {}\nvoid testSubtract() {}"
    result = _detect_coverage(code, "java")
    assert "testAddNumbers()" in result
    assert "testSubtract()" in result


def test_detect_coverage_go() -> None:
    code = "func TestAddition(t *testing.T) {}\nfunc TestSubtract(t *testing.T) {}"
    result = _detect_coverage(code, "go")
    assert "TestAddition()" in result
    assert "TestSubtract()" in result


def test_detect_coverage_rust() -> None:
    code = "fn test_something() {}\nfn test_another() {}"
    result = _detect_coverage(code, "rust")
    assert "something()" in result
    assert "another()" in result


def test_detect_coverage_ruby() -> None:
    code = "it 'does the thing' do end\ndescribe 'MyClass' do end"
    result = _detect_coverage(code, "ruby")
    assert any("does the thing" in r for r in result)


def test_detect_coverage_empty_content() -> None:
    assert _detect_coverage("", "python") == []


def test_detect_coverage_unknown_lang() -> None:
    assert _detect_coverage("some code", None) == []


# ---------------------------------------------------------------------------
# _detect_mocks
# ---------------------------------------------------------------------------


def test_detect_mocks_python_patch() -> None:
    code = "@patch('myapp.services.EmailService')\ndef test_send(mock_email): pass"
    result = _detect_mocks(code, "python")
    assert "EmailService" in result


def test_detect_mocks_python_mock_spec() -> None:
    code = "svc = Mock(spec=UserService)\n"
    result = _detect_mocks(code, "python")
    assert "UserService" in result


def test_detect_mocks_python_mocker_patch() -> None:
    code = "mocker.patch('myapp.db.Database')\n"
    result = _detect_mocks(code, "python")
    assert "Database" in result


def test_detect_mocks_python_max_4() -> None:
    code = "\n".join(f"@patch('app.module.Service{i}')\ndef test_{i}(m): pass" for i in range(6))
    result = _detect_mocks(code, "python")
    assert len(result) <= 4


def test_detect_mocks_javascript() -> None:
    code = "vi.mock('../../services/api');\njest.mock('../utils/logger');"
    result = _detect_mocks(code, "javascript")
    assert "api" in result
    assert "logger" in result


def test_detect_mocks_java() -> None:
    code = "@Mock\nprivate UserRepository userRepository;"
    result = _detect_mocks(code, "java")
    assert "userRepository" in result


def test_detect_mocks_empty_returns_empty() -> None:
    assert _detect_mocks("", "python") == []


def test_detect_mocks_unknown_lang_returns_empty() -> None:
    assert _detect_mocks("mock stuff", None) == []


# ---------------------------------------------------------------------------
# _build_header
# ---------------------------------------------------------------------------


def test_build_header_python_validated() -> None:
    content = "def test_add():\n    assert 1 + 1 == 2\n"
    header = _build_header(
        "tests/test_add.py", content, statuses={"tests/test_add.py": "validated"}
    )
    assert "# [AQUILA] status: validated" in header
    assert "# [AQUILA] coverage:" in header


def test_build_header_java_uses_double_slash() -> None:
    content = "void testSomething() {}\n" * 10
    header = _build_header(
        "src/test/java/AppTest.java",
        content,
        statuses={"src/test/java/AppTest.java": "syntax-only"},
    )
    assert "// [AQUILA] status:" in header


def test_build_header_cobol_uses_star() -> None:
    content = "IDENTIFICATION DIVISION.\n"
    header = _build_header("tests/prog_stub.cbl", content)
    assert "* [AQUILA]" in header


def test_build_header_ruby_uses_hash() -> None:
    content = "it 'works' do; end\n" * 3
    header = _build_header("spec/app_spec.rb", content, statuses={"spec/app_spec.rb": "validated"})
    assert "# [AQUILA] status: validated" in header


def test_build_header_mocks_line_present_when_mocks_detected() -> None:
    content = "@patch('app.module.Repo')\ndef test_x(m):\n    pass\n"
    header = _build_header("tests/test_x.py", content, statuses={"tests/test_x.py": "validated"})
    assert "# [AQUILA] mocks:" in header
    assert "Repo" in header


def test_build_header_no_mocks_line_when_no_mocks() -> None:
    content = "def test_basic():\n    assert True\n"
    header = _build_header(
        "tests/test_basic.py", content, statuses={"tests/test_basic.py": "validated"}
    )
    assert "mocks:" not in header


def test_build_header_ends_with_blank_line() -> None:
    content = "def test_x():\n    pass\n"
    header = _build_header("tests/test_x.py", content, statuses={"tests/test_x.py": "validated"})
    assert header.endswith("\n")


# ---------------------------------------------------------------------------
# _build_readme
# ---------------------------------------------------------------------------


def test_build_readme_contains_repo_id() -> None:
    files = {"tests/test_app.py": "def test_x(): pass\n"}
    frameworks = {"pytest": "Python"}
    readme = _build_readme("my-repo", "per_file", frameworks, files)
    assert "my-repo" in readme


def test_build_readme_contains_scope() -> None:
    files = {"tests/test_app.py": "def test_x(): pass\n"}
    readme = _build_readme("repo", "per_module", {"pytest": "Python"}, files)
    assert "per_module" in readme


def test_build_readme_contains_framework_install_commands() -> None:
    files = {"tests/test_app.py": ""}
    readme = _build_readme("repo", "per_file", {"pytest": "Python"}, files)
    assert "pip install pytest" in readme
    assert "pytest" in readme


def test_build_readme_contains_coverage_table() -> None:
    files = {"tests/test_app.py": "def test_add(): pass\n"}
    readme = _build_readme("repo", "per_file", {"pytest": "Python"}, files)
    assert "test_app.py" in readme
    assert "Status" in readme


# ---------------------------------------------------------------------------
# build_test_zip — integration
# ---------------------------------------------------------------------------


def _simple_files() -> dict[str, str]:
    return {
        "tests/test_app.py": "def test_basic():\n    assert True\n",
        "tests/test_utils.py": "def test_util():\n    assert 1 + 1 == 2\n",
    }


def test_build_test_zip_returns_bytes_io() -> None:
    buf = build_test_zip(_simple_files(), "per_file", "my-repo")
    assert isinstance(buf, io.BytesIO)
    assert buf.tell() == 0  # seeked to start


def test_build_test_zip_is_valid_zip() -> None:
    buf = build_test_zip(_simple_files(), "per_file", "my-repo")
    assert zipfile.is_zipfile(buf)


def test_build_test_zip_contains_readme() -> None:
    buf = build_test_zip(_simple_files(), "per_file", "my-repo")
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
    assert "README.md" in names


def test_build_test_zip_contains_all_files() -> None:
    files = _simple_files()
    buf = build_test_zip(files, "per_file", "my-repo")
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
    for path in files:
        assert path in names


def test_build_test_zip_files_have_aquila_header() -> None:
    files = {"tests/test_app.py": "def test_x():\n    pass\n"}
    buf = build_test_zip(files, "per_file", "repo", statuses={"tests/test_app.py": "validated"})
    with zipfile.ZipFile(buf) as zf:
        content = zf.read("tests/test_app.py").decode("utf-8")
    assert "# [AQUILA]" in content


def test_build_test_zip_readme_has_repo_id() -> None:
    buf = build_test_zip(_simple_files(), "per_file", "special-repo")
    with zipfile.ZipFile(buf) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "special-repo" in readme


def test_build_test_zip_with_statuses() -> None:
    files = {"tests/test_x.py": "def test_x():\n    assert True\n"}
    statuses = {"tests/test_x.py": "validated"}
    buf = build_test_zip(files, "per_file", "repo", statuses=statuses)
    with zipfile.ZipFile(buf) as zf:
        content = zf.read("tests/test_x.py").decode("utf-8")
    assert "status: validated" in content


def test_build_test_zip_empty_files() -> None:
    buf = build_test_zip({}, "per_file", "empty-repo")
    assert zipfile.is_zipfile(buf)
    with zipfile.ZipFile(buf) as zf:
        assert "README.md" in zf.namelist()
        assert len(zf.namelist()) == 1
