"""Security scanner orchestration.

Flow:
1. Resolve source to a local path (pass-through for local, clone for remote).
2. Run all static tools in parallel (semgrep, gitleaks, trivy, checkov).
3. Group raw findings by file.
4. LLM triage: filter false positives, confirm exploitability, detect logic vulns.
5. Assemble Markdown report.
6. Return ScanResult.

Coverage:
- SAST         : semgrep
- Secrets       : gitleaks
- SCA           : trivy (pip/npm/cargo/maven/go/…)
- Container     : trivy (Dockerfile configs)
- IaC           : trivy + checkov (Terraform, K8s, Helm, GHA, …)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from ._checkov import is_checkov_available, run_checkov
from ._clone import resolve_source
from ._findings import Finding, ScanResult
from ._gitleaks import is_gitleaks_available, run_gitleaks
from ._llm import triage_findings
from ._report import build_report
from ._semgrep import is_semgrep_available, run_semgrep
from ._trivy import is_trivy_available, run_trivy

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

logger = logging.getLogger("aquila.security.scanner")


def scan(
    source: str,
    repo_id: str,
    svc: KnowledgeService | None = None,
    token: str = "",
    branch: str = "",
    semgrep_config: str = "auto",
    run_llm_triage: bool = True,
    progress_callback: Callable[[int, int, str | None], None] | None = None,
) -> ScanResult:
    """Run a full two-layer security scan.

    Args:
        source: Local directory path or remote git URL.
        repo_id: Repository identifier (used for LLM context lookup).
        svc: KnowledgeService for code context retrieval. Optional.
        token: OAuth/PAT token for private remote repos.
        branch: Branch/tag to check out (remote clones only).
        semgrep_config: Semgrep rule config (default ``auto``).
        run_llm_triage: If False, skip LLM pass (static tools only).
        progress_callback: ``(completed, total, label)`` callback.

    Returns:
        :class:`ScanResult` with findings, report, and stats.
    """
    progress_callback and progress_callback(0, 4, "Resolving source…")

    semgrep_ok = is_semgrep_available()
    gitleaks_ok = is_gitleaks_available()
    trivy_ok = is_trivy_available()
    checkov_ok = is_checkov_available()

    if not any([semgrep_ok, gitleaks_ok, trivy_ok, checkov_ok]):
        raise RuntimeError(
            "No security analysis tools found on the server.\n"
            "Install at least one:\n"
            "  pip install semgrep checkov\n"
            "  # trivy / gitleaks: see Dockerfile or scripts/install-security-tools.sh"
        )

    tools_used: list[str] = []
    if semgrep_ok:
        tools_used.append("semgrep")
    if gitleaks_ok:
        tools_used.append("gitleaks")
    if trivy_ok:
        tools_used.append("trivy")
    if checkov_ok:
        tools_used.append("checkov")
    if run_llm_triage:
        tools_used.append("LLM triage")

    with resolve_source(source, token=token, branch=branch) as local_path:
        progress_callback and progress_callback(1, 4, "Running static analysis…")
        raw_findings = _run_static_tools(local_path, semgrep_config)

    progress_callback and progress_callback(2, 4, "Running LLM triage…")
    if run_llm_triage and svc is not None:
        findings_by_file: dict[str, list[Finding]] = {}
        for f in raw_findings:
            findings_by_file.setdefault(f.file, []).append(f)

        def _llm_progress(completed: int, total: int, label: str | None) -> None:
            progress_callback and progress_callback(2, 4, label)

        findings = triage_findings(findings_by_file, svc, repo_id, _llm_progress)
    else:
        # No LLM — mark all findings as unconfirmed
        findings = raw_findings

    progress_callback and progress_callback(3, 4, "Assembling report…")
    report = build_report(findings, repo_id, source, tools_used)

    severity_counts = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    progress_callback and progress_callback(4, 4, None)

    logger.info(
        "scan complete: repo=%s findings=%d critical=%d major=%d minor=%d",
        repo_id,
        len(findings),
        severity_counts["critical"],
        severity_counts["major"],
        severity_counts["minor"],
    )

    return ScanResult(
        findings=findings,
        report=report,
        stats={**severity_counts, "total": len(findings)},
        tools_used=tools_used,
    )


def _run_static_tools(local_path: str, semgrep_config: str) -> list[Finding]:
    """Run all static tools in parallel and merge results."""
    results: list[Finding] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures: dict[Any, str] = {}
        if is_semgrep_available():
            futures[executor.submit(run_semgrep, local_path, semgrep_config)] = "semgrep"
        if is_gitleaks_available():
            futures[executor.submit(run_gitleaks, local_path)] = "gitleaks"
        if is_trivy_available():
            futures[executor.submit(run_trivy, local_path)] = "trivy"
        if is_checkov_available():
            futures[executor.submit(run_checkov, local_path)] = "checkov"

        for future in as_completed(futures):
            tool = futures[future]
            try:
                results.extend(future.result())
            except Exception as exc:
                logger.warning("%s failed: %s", tool, exc)

    return results
