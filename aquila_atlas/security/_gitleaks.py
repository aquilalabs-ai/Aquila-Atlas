"""Gitleaks subprocess runner with graceful degradation."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile

from ._findings import Finding

logger = logging.getLogger("aquila.security.gitleaks")

_GITLEAKS_TIMEOUT = 120


def is_gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def run_gitleaks(path: str) -> list[Finding]:
    """Run gitleaks against *path* and return parsed findings.

    All gitleaks findings are classified as **critical** (secrets exposure).
    Returns an empty list (with a warning) when gitleaks is not installed.
    """
    if not is_gitleaks_available():
        logger.warning(
            "gitleaks not found — skipping secrets detection (install gitleaks to enable)"
        )
        return []

    # Write report to a temp file so we can capture JSON output cleanly
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        report_path = tmp.name

    try:
        cmd = [
            "gitleaks",
            "detect",
            "--source",
            path,
            "--report-format",
            "json",
            "--report-path",
            report_path,
            "--no-banner",
            "--exit-code",
            "0",  # don't fail on findings — we read the report file
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_GITLEAKS_TIMEOUT,
        )
        if result.returncode not in (0, 1):
            logger.warning("gitleaks exited %d: %s", result.returncode, result.stderr[:500])
            return []

        try:
            with open(report_path, encoding="utf-8") as fh:
                raw_text = fh.read().strip()
            data = json.loads(raw_text) if raw_text else []
        except (json.JSONDecodeError, OSError):
            logger.warning("gitleaks returned invalid/empty JSON report")
            return []

    except subprocess.TimeoutExpired:
        logger.warning("gitleaks timed out after %ds", _GITLEAKS_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("gitleaks execution failed: %s", exc)
        return []
    finally:
        with contextlib.suppress(OSError):
            os.unlink(report_path)

    findings: list[Finding] = []
    if not isinstance(data, list):
        return findings

    for raw in data:
        file_path = raw.get("File", raw.get("file", ""))
        if path and file_path.startswith(path):
            file_path = file_path[len(path) :].lstrip("/\\")

        rule_id = f"gitleaks:{raw.get('RuleID', raw.get('ruleID', 'secret'))}"
        description = raw.get("Description", raw.get("description", "Secret detected"))
        match = raw.get("Match", raw.get("match", ""))
        message = f"{description}" + (f" — matched: `{match[:80]}`" if match else "")

        findings.append(
            Finding(
                file=file_path,
                line=raw.get("StartLine", raw.get("startLine", 0)),
                rule_id=rule_id,
                severity="critical",  # all gitleaks findings are critical
                message=message,
                cwe="CWE-798",
                owasp_category="A02 - Cryptographic Failures",
                source="gitleaks",
                fingerprint=raw.get("Fingerprint", raw.get("fingerprint", "")),
            )
        )

    logger.info("gitleaks: %d findings in %s", len(findings), path)
    return findings
