"""AI-powered security scanning module.

Multi-tool scanner covering SAST, secrets, SCA, container, and IaC + LLM triage.

Tools used (all optional, graceful degradation):
  semgrep  — SAST (code patterns, injections, …)
  gitleaks — Secrets detection
  trivy    — SCA (CVEs in pip/npm/cargo/…), Dockerfile, IaC
  checkov  — IaC specialist (Terraform, CloudFormation, K8s, GHA, …)
  LLM      — Triage pass: filter FPs, confirm exploitability, suggest fixes

Public entry point: :func:`scan`.
"""

from .scanner import scan

__all__ = ["scan"]
