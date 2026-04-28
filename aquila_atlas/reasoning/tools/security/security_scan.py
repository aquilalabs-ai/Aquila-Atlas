"""SecurityScanTool — targeted security scan of a file or directory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class SecurityScanInput(BaseModel):
    target: str = Field(
        description=(
            "Local file path or directory to scan for security vulnerabilities. "
            "Examples: 'src/auth/service.py', 'src/api/', '/home/user/project'."
        )
    )
    repo_id: str = Field(description="Repository ID (for code context lookup)")
    semgrep_config: str = Field(
        default="auto",
        description="Semgrep rule config. Default 'auto'. Examples: 'p/owasp-top-ten', 'p/python'.",
    )


class SecurityScanTool(BaseTool):
    """Targeted security scan of a file or directory using semgrep + LLM triage."""

    name: str = "security_scan"
    description: str = (
        "Run a security scan on a local file or directory. "
        "Uses semgrep for pattern-based vulnerability detection and LLM analysis "
        "to filter false positives, confirm exploitability, and suggest fixes. "
        "Returns the top findings with severity, OWASP category, and fix suggestions. "
        "Use this when asked to check a specific file or module for security issues."
    )
    args_schema: type[BaseModel] = SecurityScanInput
    service: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, target: str, repo_id: str, semgrep_config: str = "auto") -> str:
        logger.debug("tool=security_scan repo=%s target=%r", repo_id, target)
        svc = cast("KnowledgeService", self.service)

        from aquila_atlas.security.scanner import scan  # noqa: PLC0415

        try:
            result = scan(
                source=target,
                repo_id=repo_id,
                svc=svc,
                semgrep_config=semgrep_config,
                run_llm_triage=True,
            )
        except Exception as exc:
            logger.warning("security_scan tool failed for %r: %s", target, exc)
            return f"Security scan failed: {exc}"

        if not result.findings:
            return (
                f"**Security Scan: `{target}`**\n\n"
                "✅ No findings detected by semgrep or gitleaks.\n\n"
                "_Note: This does not guarantee the absence of all vulnerabilities._"
            )

        counts = result.severity_counts()
        lines: list[str] = [
            f"**Security Scan: `{target}`**",
            "",
            f"🔴 Critical: {counts.get('critical', 0)} · "
            f"🟠 Major: {counts.get('major', 0)} · "
            f"🔵 Minor: {counts.get('minor', 0)}",
            "",
        ]

        # Show up to 10 most important findings
        ordered = sorted(
            result.findings,
            key=lambda f: {"critical": 0, "major": 1, "minor": 2}[f.severity],
        )
        for f in ordered[:10]:
            emoji = {"critical": "🔴", "major": "🟠", "minor": "🔵"}[f.severity]
            lines += [
                f"{emoji} **{f.severity.upper()}** `{f.file}:{f.line}` [{f.rule_id}]",
                f"   {f.message}",
                f"   *OWASP: {f.owasp_category}*",
            ]
            if f.fix_suggestion:
                lines.append(f"   **Fix:** {f.fix_suggestion[:200]}")
            lines.append("")

        if len(result.findings) > 10:
            lines.append(
                f"_…and {len(result.findings) - 10} more findings. Run a full scan for the complete report._"
            )

        return "\n".join(lines)
