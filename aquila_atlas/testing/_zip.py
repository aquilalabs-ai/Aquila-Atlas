"""Build a structured ZIP archive from generated test files.

Each file is prepended with an [AQUILA] header comment block indicating:
  - status: syntax-only | unvalidated
  - coverage: detected function names from test bodies
  - mocks: detected mock/stub class names

A README.md is generated at the zip root with:
  - Detected languages and chosen frameworks
  - Exact install + run commands per framework
  - Coverage summary table
  - Optional CI snippet (GitHub Actions)
"""

from __future__ import annotations

import io
import pathlib
import re
import zipfile

from ._frameworks import get_framework  # noqa: F401

# ---------------------------------------------------------------------------
# Comment markers by language
# ---------------------------------------------------------------------------

_COMMENT: dict[str, str] = {
    "python": "#",
    "javascript": "//",
    "typescript": "//",
    "java": "//",
    "go": "//",
    "rust": "//",
    "c#": "//",
    "csharp": "//",
    "ruby": "#",
    "kotlin": "//",
    "php": "//",
    "swift": "//",
    "scala": "//",
    "bash": "#",
    "shell": "#",
    "cobol": "*",
}

# Extension → language (for test output file detection)
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "c#",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".bats": "bash",
    ".cbl": "cobol",
    ".cob": "cobol",
}

# Framework → install/run commands
_SETUP: dict[str, dict[str, str]] = {
    "pytest": {"install": "pip install pytest pytest-mock", "run": "pytest"},
    "vitest": {"install": "npm install", "run": "npm run test  # or: npx vitest run"},
    "junit5": {
        "install": "# Add JUnit 5 to pom.xml / build.gradle",
        "run": "mvn test  # or: gradle test",
    },
    "testing": {"install": "# Built-in — no extra install needed", "run": "go test ./..."},
    "builtin": {"install": "# Built-in — no extra install needed", "run": "cargo test"},
    "xunit": {"install": "dotnet restore", "run": "dotnet test"},
    "rspec": {"install": "bundle install", "run": "bundle exec rspec"},
    "kotest": {"install": "# Add Kotest to build.gradle.kts", "run": "gradle test"},
    "phpunit": {"install": "composer install", "run": "./vendor/bin/phpunit"},
    "xctest": {
        "install": "# Open in Xcode or use xcodebuild",
        "run": "xcodebuild test -scheme YourScheme",
    },
    "scalatest": {"install": "# Add ScalaTest to build.sbt", "run": "sbt test"},
    "bats-core": {
        "install": "npm install -g bats  # or: brew install bats-core",
        "run": "bats tests/",
    },
    "stub": {
        "install": "# COBOL — requires a COBOL compiler (GnuCOBOL, IBM COBOL, etc.)",
        "run": "# Compile and run per your COBOL environment",
    },
}

# GitHub Actions runner per CI language
_GHA_SETUP: dict[str, list[str]] = {
    "python": [
        "      - uses: actions/setup-python@v5",
        "        with: { python-version: '3.12' }",
    ],
    "node": [
        "      - uses: actions/setup-node@v4",
        "        with: { node-version: '20', cache: 'npm' }",
    ],
    "java": [
        "      - uses: actions/setup-java@v4",
        "        with: { distribution: 'temurin', java-version: '21' }",
    ],
    "go": [
        "      - uses: actions/setup-go@v5",
        "        with: { go-version: '1.22' }",
    ],
    "dotnet": [
        "      - uses: actions/setup-dotnet@v4",
        "        with: { dotnet-version: '8.x' }",
    ],
    "ruby": [
        "      - uses: ruby/setup-ruby@v1",
        "        with: { bundler-cache: true }",
    ],
}

_FRAMEWORK_CI_LANG: dict[str, str | None] = {
    "pytest": "python",
    "vitest": "node",
    "junit5": "java",
    "kotest": "java",
    "scalatest": "java",
    "testing": "go",
    "builtin": None,  # Rust — no setup action needed
    "xunit": "dotnet",
    "rspec": "ruby",
}


# ---------------------------------------------------------------------------
# Header annotation helpers
# ---------------------------------------------------------------------------


def _lang_of(file_path: str) -> str | None:
    ext = pathlib.Path(file_path.replace("\\", "/")).suffix.lower()
    return _EXT_TO_LANG.get(ext)


def _comment_char(lang: str | None) -> str:
    return _COMMENT.get(lang or "", "#")


def _is_unvalidated(content: str, lang: str | None) -> bool:
    if lang == "cobol":
        return True
    lines = content.splitlines()
    if len(lines) < 8:
        return True
    stub_markers = ("# stub", "// stub", "todo", "notimplemented", "pass  # placeholder")
    lower = content.lower()
    return any(m in lower for m in stub_markers)


def _detect_coverage(content: str, lang: str | None) -> list[str]:
    """Return up to 6 likely-covered function/test identifiers."""
    covered: list[str] = []
    if lang == "python":
        for m in re.finditer(r"def (test_[a-z_0-9]+)\s*\(", content):
            name = m.group(1)[5:]  # strip "test_"
            if name:
                covered.append(f"{name}()")
    elif lang in ("javascript", "typescript"):
        for m in re.finditer(r"(?:it|test)\s*\(\s*['\"]([^'\"]{2,50})", content):
            covered.append(m.group(1)[:40])
    elif lang == "java":
        for m in re.finditer(r"void\s+(test[A-Za-z_0-9]+)\s*\(", content):
            covered.append(f"{m.group(1)}()")
    elif lang == "go":
        for m in re.finditer(r"func\s+(Test[A-Za-z_0-9]+)\s*\(", content):
            covered.append(f"{m.group(1)}()")
    elif lang == "rust":
        for m in re.finditer(r"fn\s+(test_[a-z_0-9]+)\s*\(", content):
            covered.append(f"{m.group(1)[5:]}()")
    elif lang == "ruby":
        for m in re.finditer(r"(?:it|describe)\s+['\"]([^'\"]{2,50})", content):
            covered.append(m.group(1)[:40])
    return list(dict.fromkeys(covered))[:6]


def _detect_mocks(content: str, lang: str | None) -> list[str]:
    """Return up to 4 detected mock/stub class names."""
    mocks: list[str] = []
    if lang == "python":
        for m in re.finditer(r"@patch\(['\"][\w.]+\.([\w]+)['\"]", content):
            mocks.append(m.group(1))
        for m in re.finditer(r"Mock\(spec=([\w]+)\)", content):
            mocks.append(m.group(1))
        for m in re.finditer(r"mocker\.patch\(['\"][\w.]+\.([\w]+)['\"]", content):
            mocks.append(m.group(1))
    elif lang in ("javascript", "typescript"):
        for m in re.finditer(r"(?:jest|vi)\.mock\(['\"]([^'\"]+)['\"]", content):
            mocks.append(m.group(1).split("/")[-1])
    elif lang == "java":
        for m in re.finditer(
            r"@Mock\s+(?:(?:private|protected|public)\s+)?[\w<>[\],\s]+\s+([\w]+)\s*;", content
        ):
            mocks.append(m.group(1))
    return list(dict.fromkeys(mocks))[:4]


def _resolve_status(
    file_path: str,
    content: str,
    lang: str | None,
    statuses: dict[str, str] | None,
) -> str:
    """Return the validation status for a file, preferring the known value."""
    if statuses is not None and file_path in statuses:
        return statuses[file_path]
    return "unvalidated" if _is_unvalidated(content, lang) else "syntax-only"


def _build_header(
    file_path: str,
    content: str,
    statuses: dict[str, str] | None = None,
) -> str:
    """Build the [AQUILA] header comment block for a test file."""
    lang = _lang_of(file_path)
    ch = _comment_char(lang)
    status = _resolve_status(file_path, content, lang, statuses)
    coverage = _detect_coverage(content, lang)
    mocks = _detect_mocks(content, lang)

    lines: list[str] = [
        f"{ch} [AQUILA] status: {status}",
        f"{ch} [AQUILA] coverage: {', '.join(coverage) if coverage else '(see test body)'}",
    ]
    if mocks:
        lines.append(f"{ch} [AQUILA] mocks: {', '.join(mocks)}")
    lines.append("")  # blank line separator
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# README builder
# ---------------------------------------------------------------------------


def _collect_frameworks(files: dict[str, str]) -> dict[str, str]:
    """Return {framework_name: language_display} for all detected languages in files."""
    seen_lang: set[str] = set()
    fw_map: dict[str, str] = {}
    for path in files:
        lang = _lang_of(path)
        if lang and lang not in seen_lang:
            seen_lang.add(lang)
            fw = get_framework(lang)
            if fw:
                fw_map[fw.framework] = fw.language_display
    return fw_map


def _ci_snippet(frameworks: dict[str, str]) -> str:
    """Build a GitHub Actions CI YAML snippet for the detected frameworks."""
    steps: list[str] = ["      - uses: actions/checkout@v4"]
    install_cmds: list[str] = []
    run_cmds: list[str] = []

    for fw_name in frameworks:
        ci_lang = _FRAMEWORK_CI_LANG.get(fw_name)
        if ci_lang and ci_lang in _GHA_SETUP:
            steps.extend(_GHA_SETUP[ci_lang])
        setup = _SETUP.get(fw_name, {})
        if setup.get("install") and not setup["install"].startswith("#"):
            install_cmds.append(setup["install"])
        if setup.get("run"):
            run_cmds.append(f"# {frameworks[fw_name]}: {setup['run']}")

    if install_cmds:
        steps.append(f"      - run: {install_cmds[0]}")
        for cmd in install_cmds[1:]:
            steps.append(f"      - run: {cmd}")
    for cmd in run_cmds:
        steps.append(f"      - run: {cmd}")

    steps_yaml = "\n".join(f"    {s}" for s in ["steps:"] + [f"  {s}" for s in steps])

    return f"""\
name: Aquila Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
{steps_yaml}
"""


def _build_coverage_table(
    files: dict[str, str],
    statuses: dict[str, str] | None = None,
) -> str:
    """Build a Markdown coverage summary table."""
    rows: list[str] = [
        "| File | Status | Functions covered | Mocks |",
        "|------|--------|-------------------|-------|",
    ]
    for path, content in sorted(files.items()):
        lang = _lang_of(path)
        status = _resolve_status(path, content, lang, statuses)
        coverage = _detect_coverage(content, lang)
        mocks = _detect_mocks(content, lang)
        short = pathlib.Path(path.replace("\\", "/")).name
        cov_str = ", ".join(f"`{c}`" for c in coverage[:3]) if coverage else "—"
        mock_str = ", ".join(f"`{m}`" for m in mocks[:2]) if mocks else "—"
        rows.append(f"| `{short}` | {status} | {cov_str} | {mock_str} |")
    return "\n".join(rows)


def _build_readme(
    repo_id: str,
    scope: str,
    frameworks: dict[str, str],
    files: dict[str, str],
    statuses: dict[str, str] | None = None,
) -> str:
    """Build the README.md content for the test ZIP."""
    fw_section_lines: list[str] = []
    for fw_name, lang_display in frameworks.items():
        setup = _SETUP.get(fw_name, {})
        fw_section_lines += [
            f"### {lang_display} — {fw_name}",
            "",
            "```bash",
            "# Install",
            setup.get("install", "# (see framework docs)"),
            "",
            "# Run tests",
            setup.get("run", "# (see framework docs)"),
            "```",
            "",
        ]

    table = _build_coverage_table(files, statuses)
    ci = _ci_snippet(frameworks)

    detected_langs = ", ".join(sorted(frameworks.values()))

    return f"""\
# Aquila Test Scaffold — `{repo_id}`

> **Note:** This is an AI-generated test scaffold. All tests are
> `syntax-only` (generated but not executed). Assertions may need
> review before running in CI. COBOL files are marked `unvalidated`
> and contain structural stubs only.

## Overview

- **Repository:** `{repo_id}`
- **Generation scope:** `{scope}`
- **Detected languages:** {detected_langs}
- **Total files:** {len(files)}

## Install & Run

{chr(10).join(fw_section_lines)}
## Coverage Summary

{table}

## CI Integration (GitHub Actions)

Save the following as `.github/workflows/tests.yml`:

```yaml
{ci}
```

## Status Legend

| Status | Meaning |
|--------|---------|
| `validated` | Syntax check passed (ast / compiler / interpreter) |
| `syntax-only` | Generated by AI; validator unavailable for this language |
| `unvalidated` | Stub file or failed syntax check after fix attempts |

---
*Generated by [Aquila-Atlas](https://github.com/aquilalabs-ai/Aquila-Atlas)*
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_test_zip(
    files: dict[str, str],
    scope: str,
    repo_id: str,
    statuses: dict[str, str] | None = None,
) -> io.BytesIO:
    """Build an annotated ZIP archive from generated test files.

    Args:
        files: Mapping of output path → test file content (from ``generate_tests``).
        scope: Generation scope label (``per_file``, ``per_module``, ``entry_points``).
        repo_id: Repository identifier (used in README header).
        statuses: Optional mapping of output path → validated status string
            (``"validated"``, ``"syntax-only"``, ``"unvalidated"``).  When
            provided the known status is embedded directly in the header instead
            of being re-detected from content analysis.

    Returns:
        In-memory ``BytesIO`` buffer containing the ZIP archive, seeked to position 0.
    """
    frameworks = _collect_frameworks(files)
    readme_content = _build_readme(repo_id, scope, frameworks, files, statuses)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme_content)
        for path, content in files.items():
            annotated = _build_header(path, content, statuses) + content
            zf.writestr(path, annotated)

    buf.seek(0)
    return buf
