"""GitStatusTool — show working tree status (local) or repo info (remote)."""

from __future__ import annotations

import logging
import urllib.parse as _up
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._helpers import (
    _gh_get,
    _gh_owner_repo,
    _gh_token,
    _gitea_get,
    _gitea_parts,
    _gitea_token,
    _gl_get,
    _gl_parts,
    _gl_token,
    _resolve_repo_source,
    _run_git,
)

logger = logging.getLogger("aquila.reasoning")


class GitStatusInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")


class GitStatusTool(BaseTool):
    """Show working tree status (local) or latest branch/commit info (remote)."""

    name: str = "git_status"
    description: str = (
        "For local repos: show staged, unstaged, and untracked files (git status). "
        "For remote repos (GitHub, GitLab, Gitea): show the default branch, "
        "latest commit, and available branches. "
        "Useful for understanding the current state of the repository."
    )
    args_schema: type[BaseModel] = GitStatusInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=git_status repo=%s", repo_id)
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415, TC001

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        # ── Local ────────────────────────────────────────────────────────────
        if kind == "local":
            out, err2 = _run_git(source, ["status", "--short", "--branch"])
            if err2:
                return f"git status failed: {err2}"
            if not out.strip():
                return "Working tree is clean — no staged, unstaged, or untracked changes."
            return f"git status for '{repo_id}':\n\n{out}"

        assert isinstance(source, str)

        # ── GitHub ───────────────────────────────────────────────────────────
        if kind == "github":
            parsed = _gh_owner_repo(source)
            if not parsed:
                return f"Could not parse GitHub URL: {source}"
            owner, repo = parsed
            token = _gh_token()

            repo_data, err2 = _gh_get(f"/repos/{owner}/{repo}", token)
            if err2:
                return f"git status failed: {err2}"
            assert isinstance(repo_data, dict)
            default_branch = str(repo_data.get("default_branch", "main"))
            stars = repo_data.get("stargazers_count", 0)
            forks = repo_data.get("forks_count", 0)
            open_issues = repo_data.get("open_issues_count", 0)

            commit_data, _ = _gh_get(f"/repos/{owner}/{repo}/commits/{default_branch}", token)
            latest = ""
            if isinstance(commit_data, dict):
                sha = str(commit_data.get("sha", ""))[:7]
                info = commit_data.get("commit", {})
                msg = str(info.get("message", "")).splitlines()[0]
                author = info.get("author") or {}
                name = str(author.get("name", ""))
                date = str(author.get("date", ""))[:10]
                latest = f"\nLatest commit on {default_branch}: {sha}  {date}  {name}  {msg}"

            branches_data, _ = _gh_get(f"/repos/{owner}/{repo}/branches?per_page=50", token)
            branch_list = ""
            if isinstance(branches_data, list):
                names = [str(b.get("name", "")) for b in branches_data]
                branch_list = "\nBranches: " + ", ".join(names)

            return (
                f"git status for '{repo_id}' (GitHub — no working tree):\n"
                f"  Repository:     {owner}/{repo}\n"
                f"  Default branch: {default_branch}\n"
                f"  Stars: {stars}  Forks: {forks}  Open issues: {open_issues}"
                f"{latest}{branch_list}"
            )

        # ── GitLab ───────────────────────────────────────────────────────────
        if kind == "gitlab":
            parts = _gl_parts(source)
            if not parts:
                return (
                    f"Cannot query the GitLab API for SSH-cloned repo '{repo_id}'. "
                    "Re-ingest using an HTTPS URL to enable git tool support."
                )
            api_base, proj_path, proj_id = parts
            token = _gl_token()

            proj_data, err2 = _gl_get(api_base, f"/projects/{proj_id}", token)
            if err2:
                return f"git status failed: {err2}"
            assert isinstance(proj_data, dict)
            default_branch = str(proj_data.get("default_branch", "main"))
            visibility = str(proj_data.get("visibility", ""))
            stars = proj_data.get("star_count", 0)
            forks = proj_data.get("forks_count", 0)

            # Latest commit on default branch
            commit_data, _ = _gl_get(
                api_base,
                f"/projects/{proj_id}/repository/commits/{_up.quote(default_branch, safe='')}",
                token,
            )
            latest = ""
            if isinstance(commit_data, dict):
                sha = str(commit_data.get("id", ""))[:7]
                msg = str(commit_data.get("message", "")).splitlines()[0]
                name = str(commit_data.get("author_name", ""))
                date = str(commit_data.get("authored_date", ""))[:10]
                latest = f"\nLatest commit on {default_branch}: {sha}  {date}  {name}  {msg}"

            # Branch list
            branches_data, _ = _gl_get(
                api_base, f"/projects/{proj_id}/repository/branches?per_page=50", token
            )
            branch_list = ""
            if isinstance(branches_data, list):
                names = sorted(str(b.get("name", "")) for b in branches_data)
                branch_list = "\nBranches: " + ", ".join(names)

            return (
                f"git status for '{repo_id}' (GitLab — no working tree):\n"
                f"  Repository:     {proj_path}\n"
                f"  Default branch: {default_branch}\n"
                f"  Visibility: {visibility}  Stars: {stars}  Forks: {forks}"
                f"{latest}{branch_list}"
            )

        # ── Gitea / Forgejo ──────────────────────────────────────────────────
        if kind == "gitea":
            parts_g = _gitea_parts(source)
            if not parts_g:
                return (
                    f"Cannot query the Gitea API for SSH-cloned repo '{repo_id}'. "
                    "Re-ingest using an HTTPS URL to enable git tool support."
                )
            api_base, owner, repo = parts_g
            token = _gitea_token()

            repo_data, err2 = _gitea_get(api_base, f"/repos/{owner}/{repo}", token)
            if err2:
                return f"git status failed: {err2}"
            assert isinstance(repo_data, dict)
            default_branch = str(repo_data.get("default_branch", "main"))
            stars = repo_data.get("stars_count", 0)
            forks = repo_data.get("forks_count", 0)
            private = repo_data.get("private", False)

            # Latest commit
            commit_data, _ = _gitea_get(
                api_base,
                f"/repos/{owner}/{repo}/branches/{_up.quote(default_branch, safe='')}",
                token,
            )
            latest = ""
            if isinstance(commit_data, dict):
                c = commit_data.get("commit", {})
                sha = str(c.get("id", ""))[:7]
                msg = str(c.get("message", "")).splitlines()[0]
                added = c.get("added", "")
                date = str(c.get("timestamp", ""))[:10]
                latest = f"\nLatest commit on {default_branch}: {sha}  {date}  {added}  {msg}"

            # Branch list
            branches_data, _ = _gitea_get(
                api_base, f"/repos/{owner}/{repo}/branches?limit=50", token
            )
            branch_list = ""
            if isinstance(branches_data, list):
                names = sorted(str(b.get("name", "")) for b in branches_data)
                branch_list = "\nBranches: " + ", ".join(names)

            visibility = "private" if private else "public"
            return (
                f"git status for '{repo_id}' (Gitea — no working tree):\n"
                f"  Repository:     {owner}/{repo}\n"
                f"  Default branch: {default_branch}\n"
                f"  Visibility: {visibility}  Stars: {stars}  Forks: {forks}"
                f"{latest}{branch_list}"
            )

        return f"Unsupported source kind '{kind}' for repo '{repo_id}'."
