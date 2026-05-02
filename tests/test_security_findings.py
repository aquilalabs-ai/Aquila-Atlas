"""Tests for security/_findings.py — Finding model, severity helpers, OWASP mapping."""

from __future__ import annotations

import pytest

from aquila_atlas.security._findings import (
    OWASP_UNKNOWN,
    Finding,
    ScanResult,
    clamp_llm_severity,
    infer_owasp,
    semgrep_severity,
    tool_severity,
)

# ---------------------------------------------------------------------------
# infer_owasp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id, message, expected",
    [
        # A01 — Broken Access Control
        ("python.path-traversal.taint", "", "A01 - Broken Access Control"),
        ("directory-traversal-check", "", "A01 - Broken Access Control"),
        ("idor-check", "possible IDOR detected", "A01 - Broken Access Control"),
        # A02 — Cryptographic Failures
        ("hardcoded-password", "", "A02 - Cryptographic Failures"),
        ("weak-hash-md5", "uses MD5 which is insecure", "A02 - Cryptographic Failures"),
        ("generic", "secret found in source", "A02 - Cryptographic Failures"),
        # A03 — Injection
        ("sql-injection", "", "A03 - Injection"),
        ("xss-reflected", "cross-site scripting", "A03 - Injection"),
        ("command-injection-exec", "", "A03 - Injection"),
        ("template-injection-jinja2", "", "A03 - Injection"),
        # A05 — Security Misconfiguration
        ("cors-misconfiguration", "", "A05 - Security Misconfiguration"),
        ("docker.privileged-container", "", "A05 - Security Misconfiguration"),
        ("kubernetes.root-user", "", "A05 - Security Misconfiguration"),
        ("terraform-misconfig", "", "A05 - Security Misconfiguration"),
        # A06 — Vulnerable and Outdated Components
        ("cve-2023-1234", "", "A06 - Vulnerable and Outdated Components"),
        ("outdated-dependency", "", "A06 - Vulnerable and Outdated Components"),
        # A07 — Identification and Authentication Failures
        ("jwt-none-algorithm", "", "A07 - Identification and Authentication Failures"),
        ("weak-password-policy", "", "A07 - Identification and Authentication Failures"),
        # A08 — Software and Data Integrity Failures
        ("pickle-deserialization", "", "A08 - Software and Data Integrity Failures"),
        ("github-actions-workflow", "", "A08 - Software and Data Integrity Failures"),
        # A09 — Security Logging
        ("logging-check", "", "A09 - Security Logging and Monitoring Failures"),
        # A10 — SSRF
        ("ssrf-detector", "", "A10 - Server-Side Request Forgery"),
        ("server-request-forgery", "", "A10 - Server-Side Request Forgery"),
        # Unknown / no match
        ("unrelated-rule", "nothing special here", OWASP_UNKNOWN),
        ("", "", OWASP_UNKNOWN),
    ],
)
def test_infer_owasp(rule_id: str, message: str, expected: str) -> None:
    assert infer_owasp(rule_id, message) == expected


def test_infer_owasp_case_insensitive() -> None:
    assert infer_owasp("SQL-INJECTION", "SQL statement found") == "A03 - Injection"


def test_infer_owasp_rule_id_takes_priority() -> None:
    # Rule ID contains "sql" even if message has no match
    result = infer_owasp("python.sql.query", "")
    assert result == "A03 - Injection"


# ---------------------------------------------------------------------------
# semgrep_severity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level, expected",
    [
        ("ERROR", "critical"),
        ("error", "critical"),
        ("WARNING", "major"),
        ("warning", "major"),
        ("INFO", "minor"),
        ("info", "minor"),
        ("UNKNOWN_LEVEL", "minor"),  # fallback
        ("", "minor"),
    ],
)
def test_semgrep_severity(level: str, expected: str) -> None:
    assert semgrep_severity(level) == expected


# ---------------------------------------------------------------------------
# tool_severity (trivy / checkov)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level, expected",
    [
        ("CRITICAL", "critical"),
        ("critical", "critical"),
        ("HIGH", "major"),
        ("high", "major"),
        ("MEDIUM", "minor"),
        ("LOW", "minor"),
        ("UNKNOWN", "minor"),
        ("GARBAGE", "minor"),  # fallback
    ],
)
def test_tool_severity(level: str, expected: str) -> None:
    assert tool_severity(level) == expected


# ---------------------------------------------------------------------------
# clamp_llm_severity
# ---------------------------------------------------------------------------


def test_clamp_llm_cannot_assign_critical_from_minor() -> None:
    # LLM proposes critical for a minor finding — must be clamped to major
    assert clamp_llm_severity("minor", "critical") == "major"


def test_clamp_llm_cannot_assign_critical_from_major() -> None:
    assert clamp_llm_severity("major", "critical") == "major"


def test_clamp_llm_critical_stays_critical() -> None:
    # Static tool found critical; LLM agrees — allowed
    assert clamp_llm_severity("critical", "critical") == "critical"


def test_clamp_llm_can_promote_minor_to_major() -> None:
    assert clamp_llm_severity("minor", "major") == "major"


def test_clamp_llm_can_demote_critical_to_major() -> None:
    assert clamp_llm_severity("critical", "major") == "major"


def test_clamp_llm_can_demote_critical_to_minor() -> None:
    assert clamp_llm_severity("critical", "minor") == "minor"


def test_clamp_llm_major_stays_major() -> None:
    assert clamp_llm_severity("major", "major") == "major"


def test_clamp_llm_minor_stays_minor() -> None:
    assert clamp_llm_severity("minor", "minor") == "minor"


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


def _make_finding(**kwargs: object) -> Finding:
    defaults: dict[str, object] = {
        "file": "src/app.py",
        "line": 42,
        "rule_id": "python.sql.query",
        "severity": "major",
        "message": "Possible SQL injection",
    }
    defaults.update(kwargs)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_finding_defaults() -> None:
    f = _make_finding()
    assert f.cwe == ""
    assert f.owasp_category == OWASP_UNKNOWN
    assert f.fix_suggestion == ""
    assert f.source == "semgrep"
    assert f.confirmed_by_llm is False
    assert f.fingerprint == ""


def test_finding_full_construction() -> None:
    f = Finding(
        file="auth.py",
        line=10,
        rule_id="hardcoded-secret",
        severity="critical",
        message="Hardcoded password",
        cwe="CWE-798",
        owasp_category="A02 - Cryptographic Failures",
        fix_suggestion="Use environment variables",
        source="gitleaks",
        confirmed_by_llm=True,
        fingerprint="abc123",
    )
    assert f.severity == "critical"
    assert f.source == "gitleaks"
    assert f.confirmed_by_llm is True
    assert f.fingerprint == "abc123"


def test_finding_to_dict_roundtrip() -> None:
    f = _make_finding(
        cwe="CWE-89",
        owasp_category="A03 - Injection",
        fix_suggestion="Use parameterised queries",
        source="semgrep",
        confirmed_by_llm=True,
        fingerprint="fp1",
    )
    d = f.to_dict()
    assert isinstance(d, dict)
    assert d["file"] == "src/app.py"
    assert d["line"] == 42
    assert d["severity"] == "major"
    assert d["cwe"] == "CWE-89"
    assert d["confirmed_by_llm"] is True

    restored = Finding.from_dict(d)
    assert restored.file == f.file
    assert restored.line == f.line
    assert restored.rule_id == f.rule_id
    assert restored.severity == f.severity
    assert restored.cwe == f.cwe
    assert restored.confirmed_by_llm == f.confirmed_by_llm
    assert restored.fingerprint == f.fingerprint


def test_finding_from_dict_missing_keys() -> None:
    # from_dict should tolerate missing optional fields
    f = Finding.from_dict(
        {"file": "x.py", "line": 0, "rule_id": "r", "severity": "minor", "message": "m"}
    )
    assert f.cwe == ""
    assert f.fix_suggestion == ""
    assert f.confirmed_by_llm is False


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------


def test_scan_result_empty() -> None:
    sr = ScanResult()
    counts = sr.severity_counts()
    assert counts == {"critical": 0, "major": 0, "minor": 0}


def test_scan_result_severity_counts() -> None:
    findings = [
        _make_finding(severity="critical"),
        _make_finding(severity="critical"),
        _make_finding(severity="major"),
        _make_finding(severity="minor"),
        _make_finding(severity="minor"),
        _make_finding(severity="minor"),
    ]
    sr = ScanResult(findings=findings)
    counts = sr.severity_counts()
    assert counts["critical"] == 2
    assert counts["major"] == 1
    assert counts["minor"] == 3


def test_scan_result_with_report_and_tools() -> None:
    sr = ScanResult(
        findings=[_make_finding()],
        report="# Security Report\n\nFound 1 issue.",
        tools_used=["semgrep", "gitleaks"],
    )
    assert "Security Report" in sr.report
    assert "semgrep" in sr.tools_used
    assert len(sr.findings) == 1
