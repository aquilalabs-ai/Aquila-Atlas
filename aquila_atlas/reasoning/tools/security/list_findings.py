"""ListFindingsTool — query persisted findings from the last security scan."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

_SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}


class ListFindingsInput(BaseModel):
    repo_id: str = Field(description="Repository ID to query findings for")
    severity: str | None = Field(
        default=None,
        description=(
            "Filter by severity: 'critical', 'major', or 'minor'. Omit to return all severities."
        ),
    )
    owasp_category: str | None = Field(
        default=None,
        description=(
            "Filter by OWASP category substring, e.g. 'Injection', 'Access Control'. "
            "Case-insensitive. Omit to return all categories."
        ),
    )
    limit: int = Field(
        default=20,
        description="Maximum number of findings to return (default 20, max 100).",
    )


class ListFindingsTool(BaseTool):
    """Query findings from the most recent persisted security scan for a repo."""

    name: str = "list_security_findings"
    description: str = (
        "List security findings from the most recent scan for a repository. "
        "Filter by severity (critical/major/minor) or OWASP category. "
        "Use this to answer questions like 'what are the critical vulnerabilities in repo X?' "
        "or 'show me all injection findings'."
    )
    args_schema: type[BaseModel] = ListFindingsInput
    security_store: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        severity: str | None = None,
        owasp_category: str | None = None,
        limit: int = 20,
    ) -> str:
        logger.debug(
            "tool=list_security_findings repo=%s severity=%r owasp=%r",
            repo_id,
            severity,
            owasp_category,
        )

        if self.security_store is None:
            return (
                "Security store is not available. "
                "Submit a scan first via `POST /repos/{repo_id}/security/scan` "
                "or use the `security_scan` tool."
            )

        from aquila_atlas.api.store import SecurityStore  # noqa: PLC0415

        if not isinstance(self.security_store, SecurityStore):
            return "Security store type mismatch — cannot query findings."

        scans = self.security_store.list_repo_scans(repo_id)
        if not scans:
            return (
                f"No security scans found for repo `{repo_id}`. "
                "Run a scan first with the `security_scan` tool."
            )

        # Load the most recent scan
        latest_job_id = scans[0]["job_id"]
        row = self.security_store.load_scan(latest_job_id)
        if row is None:
            return "Could not load findings from the most recent scan."

        findings: list[dict[str, Any]] = row.get("findings", [])

        # Apply filters
        if severity:
            findings = [f for f in findings if f.get("severity") == severity.lower()]
        if owasp_category:
            needle = owasp_category.lower()
            findings = [f for f in findings if needle in f.get("owasp_category", "").lower()]

        if not findings:
            filters = []
            if severity:
                filters.append(f"severity={severity}")
            if owasp_category:
                filters.append(f"owasp_category contains '{owasp_category}'")
            filter_str = " AND ".join(filters) if filters else "any filter"
            return f"No findings matching {filter_str} in the latest scan for repo `{repo_id}`."

        limit = min(limit, 100)
        findings = sorted(findings, key=lambda f: _SEV_ORDER.get(f.get("severity", "minor"), 2))
        total = len(findings)
        findings = findings[:limit]

        scan_date = scans[0].get("created_at", "unknown date")
        counts = row.get("severity_counts", {})
        lines: list[str] = [
            f"**Security findings for `{repo_id}`** (scan: {scan_date})",
            f"Total in scan: 🔴 {counts.get('critical', 0)} critical · "
            f"🟠 {counts.get('major', 0)} major · "
            f"🔵 {counts.get('minor', 0)} minor",
            f"Showing {len(findings)} of {total} matching findings:",
            "",
        ]

        for f in findings:
            sev = f.get("severity", "minor")
            emoji = {"critical": "🔴", "major": "🟠", "minor": "🔵"}.get(sev, "🔵")
            lines += [
                f"{emoji} **{sev.upper()}** — `{f.get('file', '?')}:{f.get('line', 0)}`",
                f"   Rule: `{f.get('rule_id', '?')}` · OWASP: {f.get('owasp_category', '?')}",
                f"   {f.get('message', '')}",
            ]
            fix = f.get("fix_suggestion", "")
            if fix:
                lines.append(f"   **Fix:** {fix[:200]}")
            lines.append("")

        return "\n".join(lines)
