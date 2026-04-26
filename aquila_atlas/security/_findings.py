"""Finding data model and severity helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

SeverityLevel = Literal["minor", "major", "critical"]
FindingSource = Literal["semgrep", "gitleaks", "trivy", "checkov", "llm"]

# OWASP Top 10 (2021) categories
OWASP_UNKNOWN = "A00 - Uncategorised"
OWASP_CATEGORIES = [
    "A01 - Broken Access Control",
    "A02 - Cryptographic Failures",
    "A03 - Injection",
    "A04 - Insecure Design",
    "A05 - Security Misconfiguration",
    "A06 - Vulnerable and Outdated Components",
    "A07 - Identification and Authentication Failures",
    "A08 - Software and Data Integrity Failures",
    "A09 - Security Logging and Monitoring Failures",
    "A10 - Server-Side Request Forgery",
    OWASP_UNKNOWN,
]

# Keyword → OWASP category (rule IDs and tags)
_OWASP_KEYWORD_MAP: list[tuple[str, str]] = [
    # A01
    ("path-traversal", "A01 - Broken Access Control"),
    ("directory-traversal", "A01 - Broken Access Control"),
    ("idor", "A01 - Broken Access Control"),
    ("access-control", "A01 - Broken Access Control"),
    ("broken-access", "A01 - Broken Access Control"),
    # A02
    ("crypto", "A02 - Cryptographic Failures"),
    ("hardcoded", "A02 - Cryptographic Failures"),
    ("secret", "A02 - Cryptographic Failures"),
    ("weak-hash", "A02 - Cryptographic Failures"),
    ("md5", "A02 - Cryptographic Failures"),
    ("sha1", "A02 - Cryptographic Failures"),
    # A03
    ("sql", "A03 - Injection"),
    ("injection", "A03 - Injection"),
    ("xss", "A03 - Injection"),
    ("command-injection", "A03 - Injection"),
    ("shell-injection", "A03 - Injection"),
    ("template-injection", "A03 - Injection"),
    ("ldap", "A03 - Injection"),
    ("xpath", "A03 - Injection"),
    # A05
    ("misconfiguration", "A05 - Security Misconfiguration"),
    ("xxe", "A05 - Security Misconfiguration"),
    ("cors", "A05 - Security Misconfiguration"),
    ("debug", "A05 - Security Misconfiguration"),
    ("error-handling", "A05 - Security Misconfiguration"),
    # A07
    ("auth", "A07 - Identification and Authentication Failures"),
    ("jwt", "A07 - Identification and Authentication Failures"),
    ("session", "A07 - Identification and Authentication Failures"),
    ("password", "A07 - Identification and Authentication Failures"),
    ("brute", "A07 - Identification and Authentication Failures"),
    # A08
    ("deserialization", "A08 - Software and Data Integrity Failures"),
    ("pickle", "A08 - Software and Data Integrity Failures"),
    ("marshal", "A08 - Software and Data Integrity Failures"),
    ("integrity", "A08 - Software and Data Integrity Failures"),
    # A09
    ("log-injection", "A09 - Security Logging and Monitoring Failures"),
    ("logging", "A09 - Security Logging and Monitoring Failures"),
    # A10
    ("ssrf", "A10 - Server-Side Request Forgery"),
    ("request-forgery", "A10 - Server-Side Request Forgery"),
    # A06 — dependency / SCA findings
    ("cve-", "A06 - Vulnerable and Outdated Components"),
    ("vulnerability", "A06 - Vulnerable and Outdated Components"),
    ("outdated", "A06 - Vulnerable and Outdated Components"),
    ("dependency", "A06 - Vulnerable and Outdated Components"),
    # A05 — IaC / container misconfiguration
    ("dockerfile", "A05 - Security Misconfiguration"),
    ("kubernetes", "A05 - Security Misconfiguration"),
    ("terraform", "A05 - Security Misconfiguration"),
    ("helm", "A05 - Security Misconfiguration"),
    ("cloudformation", "A05 - Security Misconfiguration"),
    ("iac", "A05 - Security Misconfiguration"),
    ("misconfig", "A05 - Security Misconfiguration"),
    ("privileged", "A05 - Security Misconfiguration"),
    ("root user", "A05 - Security Misconfiguration"),
    # A08 — supply chain / integrity
    ("supply-chain", "A08 - Software and Data Integrity Failures"),
    ("github-actions", "A08 - Software and Data Integrity Failures"),
    ("workflow", "A08 - Software and Data Integrity Failures"),
]


def infer_owasp(rule_id: str, message: str = "") -> str:
    """Infer OWASP category from rule ID and message text."""
    haystack = (rule_id + " " + message).lower()
    for keyword, category in _OWASP_KEYWORD_MAP:
        if keyword in haystack:
            return category
    return OWASP_UNKNOWN


# Semgrep severity level mapping
_SEMGREP_SEVERITY: dict[str, SeverityLevel] = {
    "ERROR": "critical",
    "WARNING": "major",
    "INFO": "minor",
}


def semgrep_severity(level: str) -> SeverityLevel:
    return _SEMGREP_SEVERITY.get(level.upper(), "minor")


# Trivy / Checkov severity mapping (shared — both use the same scale)
_TOOL_SEVERITY: dict[str, SeverityLevel] = {
    "CRITICAL": "critical",
    "HIGH": "major",
    "MEDIUM": "minor",
    "LOW": "minor",
    "UNKNOWN": "minor",
}


def tool_severity(level: str) -> SeverityLevel:
    """Map trivy/checkov severity strings to internal SeverityLevel."""
    return _TOOL_SEVERITY.get(level.upper(), "minor")


def clamp_llm_severity(original: SeverityLevel, proposed: SeverityLevel) -> SeverityLevel:
    """Apply LLM severity escalation rules.

    - LLM may promote minor → major.
    - LLM may NEVER assign critical (auto-promote blocked).
    - Demotions are unrestricted (critical → major, major → minor, etc.).
    """
    if proposed == "critical" and original != "critical":
        return "major"  # hard cap: LLM cannot assign critical
    return proposed


@dataclass
class Finding:
    file: str
    line: int
    rule_id: str
    severity: SeverityLevel
    message: str
    cwe: str = ""
    owasp_category: str = OWASP_UNKNOWN
    fix_suggestion: str = ""
    source: FindingSource = "semgrep"
    confirmed_by_llm: bool = False
    fingerprint: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, object]) -> Finding:
        return Finding(
            file=str(d.get("file", "")),
            line=int(d.get("line", 0) or 0),  # type: ignore[call-overload]
            rule_id=str(d.get("rule_id", "")),
            severity=d.get("severity", "minor"),  # type: ignore[arg-type]
            message=str(d.get("message", "")),
            cwe=str(d.get("cwe", "")),
            owasp_category=str(d.get("owasp_category", OWASP_UNKNOWN)),
            fix_suggestion=str(d.get("fix_suggestion", "")),
            source=d.get("source", "semgrep"),  # type: ignore[arg-type]
            confirmed_by_llm=bool(d.get("confirmed_by_llm", False)),
            fingerprint=str(d.get("fingerprint", "")),
        )


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    report: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)

    def severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts
