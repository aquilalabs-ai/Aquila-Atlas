"""Per-language syntax validators for generated test files.

Each validator returns ``(ok, error)``:
  ``(None, None)``    — tool not installed or language skipped  →  status: syntax-only
  ``(True, None)``    — syntax valid                            →  status: validated
  ``(False, error)``  — syntax invalid                          →  retry with fix prompt

Language coverage
-----------------
Validated (syntax check available):
  Python      ast.parse()          stdlib, zero deps
  JavaScript  node --check         requires Node.js
  TypeScript  tsc --noEmit         requires Node.js + typescript package
  Java        javac -proc:none     requires JDK
  Go          gofmt -e <file>      requires Go toolchain
  Rust        rustc --emit=metadata requires Rust toolchain
  Ruby        ruby -c              requires Ruby
  PHP         php -l               requires PHP CLI
  Bash/Shell  bash -n              requires Bash

Syntax-only (no lightweight validator; validated flag skipped intentionally):
  C# / csharp  — Roslyn compile too heavy
  Kotlin       — kotlinc startup too slow
  Swift        — no cross-platform CLI parser
  Scala        — scalac too slow for quick checks
  Bats         — bats-core syntax ≠ shell; bash -n would misfire
  COBOL        — generated as stubs only
"""

from __future__ import annotations

import ast
import json
import logging
import pathlib
import re
import subprocess
import tempfile
from typing import Any

from ._frameworks import detect_language

logger = logging.getLogger("aquila.test_validator")

_TIMEOUT = 15  # seconds per subprocess call

# Languages for which we explicitly skip validation (no suitable lightweight tool).
_SYNTAX_ONLY_LANGS = frozenset({"c#", "csharp", "kotlin", "swift", "scala", "cobol"})

# Extensions that need special-case skipping regardless of language detection.
# .bats uses bats-specific syntax (@test blocks) that bash -n rejects as syntax errors.
_SYNTAX_ONLY_EXTS = frozenset({".bats"})


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_python(content: str) -> tuple[bool | None, str | None]:
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"


def _validate_javascript(content: str, output_path: str) -> tuple[bool | None, str | None]:
    """Validate JavaScript using ``node --check``."""
    suffix = pathlib.Path(output_path).suffix or ".js"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix, mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = f.name
        result = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
        )
        return (
            (True, None)
            if result.returncode == 0
            else (False, (result.stderr or result.stdout).strip())
        )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if tmp_path:
            pathlib.Path(tmp_path).unlink(missing_ok=True)


def _validate_typescript(content: str, output_path: str) -> tuple[bool | None, str | None]:
    """Validate TypeScript using ``tsc --noEmit``.

    Writes the file and a minimal ``tsconfig.json`` to a temp directory so the
    compiler can resolve the file without requiring a real project setup.
    Falls back to ``(None, None)`` when ``tsc`` is not installed.
    """
    name = pathlib.Path(output_path).name or "test.ts"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            (tmp / name).write_text(content, encoding="utf-8")
            (tmp / "tsconfig.json").write_text(
                json.dumps(
                    {
                        "compilerOptions": {
                            "noEmit": True,
                            "skipLibCheck": True,
                            "strict": False,
                            "target": "ES2020",
                            "module": "CommonJS",
                            "allowSyntheticDefaultImports": True,
                            "esModuleInterop": True,
                        },
                        "include": [name],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["tsc", "--project", str(tmp / "tsconfig.json")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT,
                cwd=tmpdir,
            )
            return (
                (True, None)
                if result.returncode == 0
                else (False, (result.stderr or result.stdout).strip())
            )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None


def _validate_java(content: str, output_path: str) -> tuple[bool | None, str | None]:
    """Validate Java using ``javac -proc:none`` (parse-only, no classpath needed)."""
    name = pathlib.Path(output_path).name or "Test.java"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = pathlib.Path(tmpdir) / name
            src.write_text(content, encoding="utf-8")
            result = subprocess.run(
                ["javac", "-proc:none", str(src)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT,
            )
            return (
                (True, None)
                if result.returncode == 0
                else (False, (result.stderr or result.stdout).strip())
            )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None


def _validate_go(content: str) -> tuple[bool | None, str | None]:
    """Validate Go syntax using ``gofmt -e`` on a temp file.

    Writing to a file (rather than stdin) ensures the full parse cycle runs,
    including package-clause validation.
    """
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".go", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = f.name
        result = subprocess.run(
            ["gofmt", "-e", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
        )
        return (
            (True, None)
            if result.returncode == 0
            else (False, (result.stderr or result.stdout).strip())
        )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if tmp_path:
            pathlib.Path(tmp_path).unlink(missing_ok=True)


def _validate_rust(content: str, output_path: str) -> tuple[bool | None, str | None]:
    """Validate Rust using ``rustc --emit=metadata`` (parse + type-check, no binary)."""
    stem = pathlib.Path(output_path).stem or "test"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = pathlib.Path(tmpdir) / f"{stem}.rs"
            src.write_text(content, encoding="utf-8")
            result = subprocess.run(
                [
                    "rustc",
                    "--edition=2021",
                    "--emit=metadata",
                    "-o",
                    str(pathlib.Path(tmpdir) / "out.rlib"),
                    str(src),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT,
            )
            return (
                (True, None)
                if result.returncode == 0
                else (False, (result.stderr or result.stdout).strip())
            )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None


def _validate_ruby(content: str) -> tuple[bool | None, str | None]:
    """Validate Ruby syntax using ``ruby -c``."""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".rb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = f.name
        result = subprocess.run(
            ["ruby", "-c", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
        )
        return (
            (True, None)
            if result.returncode == 0
            else (False, (result.stderr or result.stdout).strip())
        )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if tmp_path:
            pathlib.Path(tmp_path).unlink(missing_ok=True)


def _validate_php(content: str) -> tuple[bool | None, str | None]:
    """Validate PHP syntax using ``php -l``."""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".php", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = f.name
        result = subprocess.run(
            ["php", "-l", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
        )
        return (
            (True, None)
            if result.returncode == 0
            else (False, (result.stderr or result.stdout).strip())
        )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if tmp_path:
            pathlib.Path(tmp_path).unlink(missing_ok=True)


def _validate_bash(content: str) -> tuple[bool | None, str | None]:
    """Validate shell script syntax using ``bash -n``.

    Only called for ``.sh`` / ``.bash`` files.  ``.bats`` files use bats-specific
    syntax (``@test`` blocks) that ``bash -n`` cannot parse — they are handled
    via the ``_SYNTAX_ONLY_EXTS`` skip list.
    """
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".sh", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp_path = f.name
        result = subprocess.run(
            ["bash", "-n", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
        )
        return (
            (True, None)
            if result.returncode == 0
            else (False, (result.stderr or result.stdout).strip())
        )
    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if tmp_path:
            pathlib.Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def validate(output_path: str, content: str) -> tuple[bool | None, str | None]:
    """Validate the syntax of a generated test file.

    Uses the file extension to detect the language (via ``_frameworks.detect_language``),
    then dispatches to the appropriate per-language validator.

    Returns:
        ``(None, None)``    — validator unavailable or language explicitly skipped
        ``(True, None)``    — syntax valid
        ``(False, error)``  — syntax invalid; *error* is a human-readable message
    """
    ext = pathlib.Path(output_path.replace("\\", "/")).suffix.lower()
    if ext in _SYNTAX_ONLY_EXTS:
        logger.debug("validator: skipping %s (extension %s is syntax-only)", output_path, ext)
        return None, None

    lang = detect_language(output_path)
    if lang is None:
        return None, None

    if lang in _SYNTAX_ONLY_LANGS:
        logger.debug("validator: skipping %s (no lightweight validator for %s)", output_path, lang)
        return None, None

    try:
        if lang == "python":
            return _validate_python(content)
        if lang == "javascript":
            return _validate_javascript(content, output_path)
        if lang == "typescript":
            return _validate_typescript(content, output_path)
        if lang == "java":
            return _validate_java(content, output_path)
        if lang == "go":
            return _validate_go(content)
        if lang == "rust":
            return _validate_rust(content, output_path)
        if lang == "ruby":
            return _validate_ruby(content)
        if lang == "php":
            return _validate_php(content)
        if lang in ("bash", "shell"):
            return _validate_bash(content)
    except Exception as exc:
        logger.debug("validator raised unexpectedly for %s: %s", output_path, exc)

    return None, None


# ---------------------------------------------------------------------------
# Code-fence stripper
# ---------------------------------------------------------------------------

# Common aliases used in markdown fences for each language.
_FENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python", "py"),
    "javascript": ("javascript", "js", "jsx"),
    "typescript": ("typescript", "ts", "tsx"),
    "java": ("java",),
    "go": ("go", "golang"),
    "rust": ("rust", "rs"),
    "ruby": ("ruby", "rb"),
    "php": ("php",),
    "c#": ("csharp", "cs", "c#"),
    "csharp": ("csharp", "cs", "c#"),
    "kotlin": ("kotlin", "kt"),
    "swift": ("swift",),
    "scala": ("scala",),
    "bash": ("bash", "sh", "shell"),
    "shell": ("bash", "sh", "shell"),
    "cobol": ("cobol", "cbl"),
}


def _strip_code_fence(text: str, language_display: str) -> str:
    """Remove an optional ``` fence from an LLM response.

    Tries aliases for the given language (e.g. ``"ts"`` for TypeScript) before
    falling back to matching any alphanumeric fence tag.
    """
    lang_key = language_display.lower()
    aliases = _FENCE_ALIASES.get(lang_key, (lang_key,))
    alias_pattern = "|".join(re.escape(a) for a in aliases)

    # Try fence with a known alias first (most precise)
    m = re.search(
        rf"```(?:{alias_pattern})\s*\n(.*?)```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # Fall back: any alphanumeric (or empty) fence tag
    m = re.search(r"```[a-zA-Z0-9#]*\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    return text.strip()


# ---------------------------------------------------------------------------
# Fix loop
# ---------------------------------------------------------------------------

_FIX_TEMPLATE: str | None = None


def _load_fix_template() -> str:
    global _FIX_TEMPLATE  # noqa: PLW0603
    if _FIX_TEMPLATE is None:
        p = pathlib.Path(__file__).parent.parent / "reasoning" / "prompts" / "test_fix.md"
        try:
            _FIX_TEMPLATE = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            _FIX_TEMPLATE = (
                "The following {language} test file has a syntax error.\n\n"
                "Error:\n```\n{error_message}\n```\n\n"
                "Original code:\n```{language_lower}\n{original_code}\n```\n\n"
                "Fix the syntax error and return ONLY the corrected code "
                "(no markdown fences, no explanation)."
            )
    return _FIX_TEMPLATE


def run_fix_loop(
    output_path: str,
    content: str,
    llm: Any,
    language_display: str,
    max_retries: int = 3,
) -> tuple[str, str]:
    """Validate *content* and attempt LLM-driven fixes on failure.

    Args:
        output_path: Destination file path (used for language detection).
        content: Initially generated test code (may include markdown fences).
        llm: LangChain chat model instance.
        language_display: Human-readable language name (e.g. ``"TypeScript"``).
        max_retries: Maximum LLM fix attempts before giving up.

    Returns:
        ``(final_content, status)`` where *status* is one of:

        * ``"validated"``   — syntax check passed
        * ``"syntax-only"`` — no validator available for this language/extension
        * ``"unvalidated"`` — still broken after *max_retries* attempts
    """
    # Strip any markdown fence the LLM may have wrapped around the code.
    content = _strip_code_fence(content, language_display)

    ok, error = validate(output_path, content)

    if ok is None:
        return content, "syntax-only"
    if ok:
        return content, "validated"

    template = _load_fix_template()
    current = content

    for attempt in range(max_retries):
        logger.debug("fix attempt %d/%d for %s: %s", attempt + 1, max_retries, output_path, error)
        prompt = (
            template.replace("{language}", language_display)
            .replace("{language_lower}", language_display.lower())
            .replace("{error_message}", error or "Syntax error")
            .replace("{original_code}", current)
        )
        try:
            out = llm.invoke(prompt)
            fixed = out.content if hasattr(out, "content") else str(out)
            fixed = _strip_code_fence(fixed, language_display)
        except Exception as exc:
            logger.warning("fix LLM call failed (attempt %d): %s", attempt + 1, exc)
            break

        ok2, error2 = validate(output_path, fixed)
        if ok2 is None:
            return fixed, "syntax-only"
        if ok2:
            logger.info("fixed %s after %d attempt(s)", output_path, attempt + 1)
            return fixed, "validated"

        current = fixed
        error = error2

    logger.info(
        "could not fix %s after %d attempt(s) — marking unvalidated", output_path, max_retries
    )
    return current, "unvalidated"
