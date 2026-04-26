"""Checkov IaC scanner: Terraform, CloudFormation, K8s, Helm, GitHub Actions, Docker.

Checkov is more specialised for IaC than trivy — it has deeper Terraform and
CloudFormation rule sets and understands provider-specific best practices.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from ._findings import Finding, infer_owasp, tool_severity

logger = logging.getLogger("aquila.security.checkov")

_CHECKOV_TIMEOUT = 300  # seconds

# Map checkov check-ID prefixes to OWASP categories
_CHECKOV_OWASP: dict[str, str] = {
    "CKV_DOCKER": "A05 - Security Misconfiguration",
    "CKV_K8S": "A05 - Security Misconfiguration",
    "CKV_AWS": "A05 - Security Misconfiguration",
    "CKV_GCP": "A05 - Security Misconfiguration",
    "CKV_AZURE": "A05 - Security Misconfiguration",
    "CKV_TF": "A05 - Security Misconfiguration",
    "CKV_CF": "A05 - Security Misconfiguration",
    "CKV_GHA": "A08 - Software and Data Integrity Failures",
    "CKV2": "A05 - Security Misconfiguration",
}


def _owasp_for_check(check_id: str, name: str) -> str:
    for prefix, category in _CHECKOV_OWASP.items():
        if check_id.startswith(prefix):
            return category
    return infer_owasp(check_id, name) or "A05 - Security Misconfiguration"


def is_checkov_available() -> bool:
    return shutil.which("checkov") is not None


def run_checkov(path: str) -> list[Finding]:
    """Run checkov against *path* and return parsed findings.

    Checkov exits 1 when failures are found — treated as normal.
    """
    if not is_checkov_available():
        logger.warning("checkov not found — skipping IaC scan (pip install checkov to enable)")
        return []

    cmd = [
        "checkov",
        "--directory",
        path,
        "--output",
        "json",
        "--quiet",
        "--compact",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CHECKOV_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("checkov timed out after %ds", _CHECKOV_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("checkov execution failed: %s", exc)
        return []

    # exit 0 = all pass, 1 = findings, others = error
    if result.returncode not in (0, 1):
        logger.warning("checkov exited %d: %s", result.returncode, result.stderr[:500])
        return []

    try:
        raw = result.stdout.strip()
        # checkov may output a list (one entry per check type) or a single dict
        data = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        logger.warning("checkov returned invalid JSON")
        return []

    # Normalise to a list of result blocks
    blocks: list[dict[str, object]] = data if isinstance(data, list) else [data]

    findings: list[Finding] = []
    seen: set[str] = set()  # deduplicate by (file, check_id)

    for block in blocks:
        results_section = block.get("results", {})
        if not isinstance(results_section, dict):
            continue
        failed: list[object] = results_section.get("failed_checks") or []
        if not isinstance(failed, list):
            continue

        for item in failed:
            if not isinstance(item, dict):
                continue

            check_id: str = str(item.get("check_id", "unknown"))
            check_meta = item.get("check", {})
            if not isinstance(check_meta, dict):
                check_meta = {}
            check_name: str = str(check_meta.get("name", check_id))
            severity_str: str = str(check_meta.get("severity") or "MEDIUM")

            file_path: str = str(item.get("file_path", ""))
            if file_path and file_path.startswith(path):
                file_path = file_path[len(path) :].lstrip("/\\")

            line_range: object = item.get("file_line_range", [0, 0])
            start_line = int(line_range[0]) if isinstance(line_range, list) and line_range else 0

            resource: str = str(item.get("resource", ""))
            guideline: str = str(item.get("guideline", ""))

            dedup_key = f"{file_path}:{check_id}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            message = f"{check_name}"
            if resource:
                message += f" (resource: {resource})"

            fix_suggestion = guideline if guideline else ""

            findings.append(
                Finding(
                    file=file_path,
                    line=start_line,
                    rule_id=check_id,
                    severity=tool_severity(severity_str),
                    message=message,
                    owasp_category=_owasp_for_check(check_id, check_name),
                    fix_suggestion=fix_suggestion,
                    source="checkov",
                )
            )

    logger.info("checkov: %d findings in %s", len(findings), path)
    return findings
