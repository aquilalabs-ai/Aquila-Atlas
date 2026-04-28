"""Trivy filesystem scanner: SCA (dependencies), container configs, and IaC.

Runs ``trivy fs --format json`` and parses two finding classes:
- **Vulnerabilities** (CVEs in package managers: pip, npm, cargo, maven, go, …)
- **Misconfigurations** (Dockerfile, Kubernetes, Terraform, Helm, …)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from ._findings import Finding, infer_owasp, tool_severity

logger = logging.getLogger("aquila.security.trivy")

_TRIVY_TIMEOUT = 300  # seconds


def is_trivy_available() -> bool:
    return shutil.which("trivy") is not None


def run_trivy(path: str) -> list[Finding]:
    """Run ``trivy fs`` against *path* and return parsed findings.

    Covers:
    - Language package vulnerabilities (pip, npm, cargo, maven, go.sum, …)
    - Container image config issues (Dockerfile)
    - IaC misconfigurations (Terraform, Kubernetes YAML, Helm, …)
    """
    if not is_trivy_available():
        logger.warning("trivy not found — skipping SCA/IaC scan (install trivy to enable)")
        return []

    cmd = [
        "trivy",
        "fs",
        "--format",
        "json",
        "--scanners",
        "vuln,misconfig,secret",
        "--quiet",
        "--no-progress",
        path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TRIVY_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("trivy timed out after %ds", _TRIVY_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("trivy execution failed: %s", exc)
        return []

    if result.returncode not in (0, 1):
        logger.warning("trivy exited %d: %s", result.returncode, result.stderr[:500])
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("trivy returned invalid JSON")
        return []

    findings: list[Finding] = []

    for scan_result in data.get("Results", []):
        target = scan_result.get("Target", "")
        rel_target = (
            target[len(path) :].lstrip("/\\") if path and target.startswith(path) else target
        )

        # ── CVEs / dependency vulnerabilities ─────────────────────────────
        for vuln in scan_result.get("Vulnerabilities") or []:
            vuln_id = vuln.get("VulnerabilityID", "unknown")
            pkg = vuln.get("PkgName", "")
            installed = vuln.get("InstalledVersion", "")
            fixed = vuln.get("FixedVersion", "")
            title = vuln.get("Title") or vuln.get("Description", "")
            severity_str = vuln.get("Severity", "UNKNOWN")
            cwe_ids: list[str] = vuln.get("CweIDs") or []
            cwe = cwe_ids[0] if cwe_ids else ""
            primary_url = vuln.get("PrimaryURL", "")

            message = f"{pkg} {installed} — {vuln_id}: {title}"
            fix_suggestion = (
                f"Upgrade {pkg} from {installed} to {fixed}."
                if fixed
                else f"No fix available yet for {vuln_id}. Monitor {primary_url} for updates."
            )

            findings.append(
                Finding(
                    file=rel_target,
                    line=0,
                    rule_id=vuln_id,
                    severity=tool_severity(severity_str),
                    message=message,
                    cwe=cwe,
                    owasp_category="A06 - Vulnerable and Outdated Components",
                    fix_suggestion=fix_suggestion,
                    source="trivy",
                )
            )

        # ── IaC / container misconfigurations ─────────────────────────────
        for mis in scan_result.get("Misconfigurations") or []:
            check_id = mis.get("ID", "unknown")
            title = mis.get("Title", "")
            message_text = mis.get("Message") or mis.get("Description", title)
            severity_str = mis.get("Severity", "UNKNOWN")
            cause = mis.get("CauseMetadata", {})
            start_line = cause.get("StartLine", 0)
            resolution = mis.get("Resolution", "")
            references: list[str] = mis.get("References") or []
            ref = references[0] if references else ""

            combined = f"{check_id} {title} {message_text}".lower()
            owasp = infer_owasp(check_id, combined) or "A05 - Security Misconfiguration"

            fix = resolution or (f"See: {ref}" if ref else "")

            findings.append(
                Finding(
                    file=rel_target,
                    line=start_line,
                    rule_id=f"trivy:{check_id}",
                    severity=tool_severity(severity_str),
                    message=f"{title}: {message_text}" if message_text != title else title,
                    owasp_category=owasp,
                    fix_suggestion=fix,
                    source="trivy",
                )
            )

    logger.info("trivy: %d findings in %s", len(findings), path)
    return findings
