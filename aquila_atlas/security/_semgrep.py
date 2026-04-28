"""Semgrep subprocess runner with graceful degradation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from ._findings import Finding, infer_owasp, semgrep_severity

logger = logging.getLogger("aquila.security.semgrep")

_SEMGREP_TIMEOUT = 300  # seconds

# Offline rulesets tried in order when 'auto' fails (requires login in semgrep >= 1.x).
_FALLBACK_CONFIGS = ["p/ci", "p/default", "p/owasp-top-ten"]


def is_semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def _run_semgrep_cmd(path: str, config: str) -> subprocess.CompletedProcess[str] | None:
    cmd = ["semgrep", "--json", f"--config={config}", path]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SEMGREP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("semgrep timed out after %ds (config=%s)", _SEMGREP_TIMEOUT, config)
        return None
    except Exception as exc:
        logger.warning("semgrep execution failed: %s", exc)
        return None


def _try_parse(
    result: subprocess.CompletedProcess[str], config: str
) -> list[dict[Any, Any]] | None:
    """Return parsed results list, or None if the run produced no usable output."""
    # semgrep exit codes: 0 = no findings, 1 = findings present,
    # 2 = findings present + some rule errors (still writes JSON in newer versions),
    # other = fatal error (e.g. auth required, network failure).
    if result.returncode not in (0, 1, 2):
        logger.debug("semgrep config=%s exited %d", config, result.returncode)
        return None

    if not result.stdout or not result.stdout.strip():
        logger.debug("semgrep config=%s exited %d with no stdout", config, result.returncode)
        return None

    try:
        data = json.loads(result.stdout)
        if result.returncode == 2 and data.get("errors"):
            logger.warning(
                "semgrep config=%s: %d rule error(s) — results may be partial",
                config,
                len(data["errors"]),
            )
        return list(data.get("results", []))
    except json.JSONDecodeError:
        logger.debug("semgrep config=%s returned invalid JSON", config)
        return None


def run_semgrep(path: str, config: str = "auto") -> list[Finding]:
    """Run semgrep against *path* and return parsed findings.

    When *config* is ``auto`` and semgrep exits without producing JSON (e.g.
    because ``auto`` requires a Semgrep login in >= 1.x), retries with offline
    fallback configs before giving up.

    Returns an empty list (with a warning) when semgrep is not installed.
    """
    if not is_semgrep_available():
        logger.warning("semgrep not found — skipping static analysis (install semgrep to enable)")
        return []

    configs_to_try = [config]
    if config == "auto":
        configs_to_try += _FALLBACK_CONFIGS

    raw_results: list[dict[Any, Any]] | None = None
    used_config = config

    for cfg in configs_to_try:
        result = _run_semgrep_cmd(path, cfg)
        if result is None:
            continue
        raw_results = _try_parse(result, cfg)
        if raw_results is not None:
            used_config = cfg
            if cfg != config:
                logger.info(
                    "semgrep: using fallback config '%s' (primary '%s' produced no output)",
                    cfg,
                    config,
                )
            break

    if raw_results is None:
        logger.warning(
            "semgrep produced no usable output for any config %s — "
            "if using 'auto', run 'semgrep login' or set SEMGREP_APP_TOKEN",
            configs_to_try,
        )
        return []

    findings: list[Finding] = []
    for raw in raw_results:
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

    logger.info("semgrep: %d findings via config '%s' in %s", len(findings), used_config, path)
    return findings
