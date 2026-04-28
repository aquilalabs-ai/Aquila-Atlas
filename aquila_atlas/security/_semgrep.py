"""Semgrep subprocess runner with graceful degradation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from ._findings import Finding, infer_owasp, semgrep_severity

logger = logging.getLogger("aquila.security.semgrep")

_SEMGREP_TIMEOUT = 300  # seconds


def is_semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def run_semgrep(path: str, config: str = "auto") -> list[Finding]:
    """Run semgrep against *path* and return parsed findings.

    Returns an empty list (with a warning) when semgrep is not installed.
    """
    if not is_semgrep_available():
        logger.warning("semgrep not found — skipping static analysis (install semgrep to enable)")
        return []

    cmd = [
        "semgrep",
        "--json",
        "--quiet",
        f"--config={config}",
        path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SEMGREP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("semgrep timed out after %ds", _SEMGREP_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("semgrep execution failed: %s", exc)
        return []

    # semgrep exits 1 when findings are present — that's normal
    if result.returncode not in (0, 1):
        logger.warning("semgrep exited %d: %s", result.returncode, result.stderr[:500])
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("semgrep returned invalid JSON")
        return []

    findings: list[Finding] = []
    for raw in data.get("results", []):
        rule_id = raw.get("check_id", "unknown")
        severity_str = raw.get("extra", {}).get("severity", "INFO")
        message = raw.get("extra", {}).get("message", "")
        meta = raw.get("extra", {}).get("metadata", {})
        cwe_raw = meta.get("cwe", "")
        cwe = cwe_raw[0] if isinstance(cwe_raw, list) else str(cwe_raw)
        owasp_raw = meta.get("owasp", "")
        owasp = (owasp_raw[0] if isinstance(owasp_raw, list) else str(owasp_raw)) or infer_owasp(
            rule_id, message
        )

        file_path = raw.get("path", "")
        # Make path relative to the scanned root when possible
        if path and file_path.startswith(path):
            file_path = file_path[len(path) :].lstrip("/\\")

        findings.append(
            Finding(
                file=file_path,
                line=raw.get("start", {}).get("line", 0),
                rule_id=rule_id,
                severity=semgrep_severity(severity_str),
                message=message,
                cwe=cwe,
                owasp_category=owasp or infer_owasp(rule_id, message),
                source="semgrep",
                fingerprint=raw.get("extra", {}).get("fingerprint", ""),
            )
        )

    logger.info("semgrep: %d findings in %s", len(findings), path)
    return findings
