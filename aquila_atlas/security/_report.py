"""Markdown report assembler for security scan results."""

from __future__ import annotations

import datetime

from ._findings import OWASP_CATEGORIES, OWASP_UNKNOWN, Finding

_SEV_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🔵",
}
_SEV_LABEL: dict[str, str] = {
    "critical": "Critical",
    "major": "Major",
    "minor": "Minor",
}


def build_report(
    findings: list[Finding],
    repo_id: str,
    source: str,
    tools_used: list[str],
) -> str:
    """Build a Markdown security report from a list of findings.

    Structure:
    - Header + scan metadata
    - Summary table (severity counts)
    - OWASP Top 10 breakdown table
    - Per-OWASP section, sorted critical → major → minor
    """
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    tools_str = ", ".join(tools_used) if tools_used else "none"

    counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    # ── Header ──────────────────────────────────────────────────────────────
    lines: list[str] = [
        f"# Security Scan Report: `{repo_id}`",
        "",
        "| Attribute | Value |",
        "|-----------|-------|",
        f"| Source | `{source}` |",
        f"| Scanned | {now} |",
        f"| Tools | {tools_str} |",
        f"| Total findings | **{len(findings)}** |",
        "",
    ]

    # ── Summary table ────────────────────────────────────────────────────────
    lines += [
        "## Summary",
        "",
        "| Severity | Count |",
        "|----------|-------|",
        f"| {_SEV_EMOJI['critical']} Critical | **{counts['critical']}** |",
        f"| {_SEV_EMOJI['major']} Major | **{counts['major']}** |",
        f"| {_SEV_EMOJI['minor']} Minor | **{counts['minor']}** |",
        f"| **Total** | **{len(findings)}** |",
        "",
    ]

    if not findings:
        lines += [
            "> ✅ No security findings detected.",
            "",
            "_This result means no patterns were matched by the configured tools. "
            "It does not guarantee the absence of all vulnerabilities._",
        ]
        return "\n".join(lines)

    # ── OWASP breakdown table ─────────────────────────────────────────────────
    owasp_counts: dict[str, dict[str, int]] = {}
    for f in findings:
        cat = f.owasp_category or OWASP_UNKNOWN
        if cat not in owasp_counts:
            owasp_counts[cat] = {"critical": 0, "major": 0, "minor": 0}
        owasp_counts[cat][f.severity] = owasp_counts[cat].get(f.severity, 0) + 1

    lines += [
        "## OWASP Top 10 Breakdown",
        "",
        "| Category | 🔴 Critical | 🟠 Major | 🔵 Minor |",
        "|----------|-------------|---------|--------|",
    ]
    ordered_cats = [c for c in OWASP_CATEGORIES if c in owasp_counts]
    for cat in ordered_cats:
        c = owasp_counts[cat]
        lines.append(
            f"| {cat} | {c.get('critical', 0)} | {c.get('major', 0)} | {c.get('minor', 0)} |"
        )
    lines.append("")

    # ── Findings by category → severity ──────────────────────────────────────
    by_category: dict[str, list[Finding]] = {}
    for f in findings:
        cat = f.owasp_category or OWASP_UNKNOWN
        by_category.setdefault(cat, []).append(f)

    lines.append("## Findings")
    lines.append("")

    for cat in ordered_cats:
        cat_findings = by_category[cat]
        lines += [f"### {cat}", ""]

        for sev in ("critical", "major", "minor"):
            sev_findings = [f for f in cat_findings if f.severity == sev]
            if not sev_findings:
                continue
            label: str = _SEV_LABEL[sev]
            emoji: str = _SEV_EMOJI[sev]
            lines += [f"#### {emoji} {label}", ""]

            for f in sev_findings:
                source_tag = f"*{f.source}*"
                cwe_tag = f" · {f.cwe}" if f.cwe else ""
                confirmed_tag = " · ✅ LLM confirmed" if f.confirmed_by_llm else ""
                lines += [
                    f"**[`{f.rule_id}`]** `{f.file}:{f.line}` {source_tag}{cwe_tag}{confirmed_tag}",
                    "",
                    f"> {f.message}",
                    "",
                ]
                if f.fix_suggestion:
                    lines += [
                        "**Fix suggestion:**",
                        "",
                        f.fix_suggestion,
                        "",
                    ]
                lines.append("---")
                lines.append("")

    return "\n".join(lines)
