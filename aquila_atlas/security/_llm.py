"""LLM triage layer for security findings."""

from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Any, cast

from ._findings import (
    OWASP_UNKNOWN,
    Finding,
    FindingSource,
    SeverityLevel,
    clamp_llm_severity,
    infer_owasp,
)

logger = logging.getLogger("aquila.security.llm")

_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "reasoning" / "prompts"

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


def _make_llm() -> Any:
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.reasoning.llm import get_chat_model  # noqa: PLC0415

    return get_chat_model(get_settings(), temperature=0.1, timeout=600)


def _load_prompt() -> str:
    path = _PROMPTS_DIR / "security_triage.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("security_triage.md prompt not found at %s", path)
        return ""


def _apply_template(template: str, **kwargs: str) -> str:
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", value)
    return template


def _parse_llm_response(
    raw: str,
    original_findings: list[Finding],
    file_path: str,
) -> list[Finding]:
    """Parse the JSON response from the LLM and return confirmed + new findings."""
    # Strip any accidental markdown fences
    cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()

    try:
        data: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON block from free text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            logger.warning("LLM returned unparseable JSON for %s — keeping originals", file_path)
            return original_findings
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("LLM JSON extraction failed for %s — keeping originals", file_path)
            return original_findings

    # Build lookup from original findings
    orig_by_rule: dict[str, Finding] = {f.rule_id: f for f in original_findings}

    results: list[Finding] = []

    for item in data.get("confirmed", []):
        if item.get("false_positive"):
            continue  # LLM says it's a FP — drop it

        rule_id = str(item.get("rule_id", ""))
        original = orig_by_rule.get(rule_id)
        original_sev: SeverityLevel = original.severity if original else "minor"
        proposed_sev = cast("SeverityLevel", item.get("severity", original_sev))
        severity = clamp_llm_severity(original_sev, proposed_sev)
        owasp = str(item.get("owasp_category") or OWASP_UNKNOWN)
        if owasp == OWASP_UNKNOWN:
            owasp = infer_owasp(rule_id, str(item.get("message", "")))

        results.append(
            Finding(
                file=file_path,
                line=int(item.get("line", 0) or 0),
                rule_id=rule_id,
                severity=severity,
                message=str(item.get("message", "")),
                cwe=str(item.get("cwe", "")),
                owasp_category=owasp,
                fix_suggestion=str(item.get("fix_suggestion", "")),
                source=cast("FindingSource", item.get("source", "semgrep")),
                confirmed_by_llm=True,
            )
        )

    for item in data.get("new_findings", []):
        proposed_sev = cast("SeverityLevel", item.get("severity", "minor"))
        # LLM-only findings default to minor; cap at major
        severity = clamp_llm_severity("minor", proposed_sev)
        owasp = str(item.get("owasp_category") or OWASP_UNKNOWN)
        if owasp == OWASP_UNKNOWN:
            owasp = infer_owasp(str(item.get("rule_id", "")), str(item.get("message", "")))

        results.append(
            Finding(
                file=file_path,
                line=int(item.get("line", 0)),
                rule_id=str(item.get("rule_id", "llm-logic")),
                severity=severity,
                message=str(item.get("message", "")),
                cwe=str(item.get("cwe", "")),
                owasp_category=owasp,
                fix_suggestion=str(item.get("fix_suggestion", "")),
                source="llm",
                confirmed_by_llm=True,
            )
        )

    return results


def triage_findings(
    findings_by_file: dict[str, list[Finding]],
    svc: KnowledgeService | None,
    repo_id: str,
    progress_callback: Any | None = None,
) -> list[Finding]:
    """Run LLM triage on all findings grouped by file.

    For each file:
    1. Retrieve code context from vector store (if svc available).
    2. Send findings + code to LLM.
    3. Parse confirmed findings and new logic-level findings.

    Gitleaks findings (secrets) are never sent to LLM triage — they are always real
    and should never be dismissed as false positives.
    """
    if not findings_by_file:
        return []

    # Separate gitleaks findings — pass them through unconditionally.
    gitleaks_findings: list[Finding] = []
    sast_by_file: dict[str, list[Finding]] = {}
    for file_path, file_findings in findings_by_file.items():
        sast = [f for f in file_findings if f.source != "gitleaks"]
        leaked = [f for f in file_findings if f.source == "gitleaks"]
        gitleaks_findings.extend(leaked)
        if sast:
            sast_by_file[file_path] = sast

    if not sast_by_file:
        return gitleaks_findings

    llm = _make_llm()
    prompt_template = _load_prompt()
    triaged: list[Finding] = list(gitleaks_findings)

    files = list(sast_by_file.keys())
    total = len(files)

    for i, file_path in enumerate(files):
        progress_callback and progress_callback(i, total, f"LLM triage: {file_path}")
        file_findings = sast_by_file[file_path]

        # Get code context for this file
        code_ctx = ""
        if svc is not None:
            try:
                results = svc.search(file_path, repo_id, top_k=10, file_path=file_path)
                if results:
                    code_ctx = "\n\n".join(
                        f"### {r.qualified_name} (lines {r.start_line}-{r.end_line})\n"
                        f"```\n{r.content}\n```"
                        for r in results
                    )
            except Exception as exc:
                logger.debug("Could not retrieve code context for %s: %s", file_path, exc)

        findings_json = json.dumps(
            [f.to_dict() for f in file_findings], indent=2, ensure_ascii=False
        )

        prompt = _apply_template(
            prompt_template,
            file_path=file_path,
            findings_json=findings_json,
            code_ctx=code_ctx or "(source not available in vector store)",
        )

        try:
            out = llm.invoke(prompt)
            raw: str = out.content if hasattr(out, "content") else str(out)
            confirmed = _parse_llm_response(raw, file_findings, file_path)
            triaged.extend(confirmed)
        except Exception as exc:
            logger.warning("LLM triage failed for %s: %s — keeping originals", file_path, exc)
            triaged.extend(file_findings)

    return triaged
