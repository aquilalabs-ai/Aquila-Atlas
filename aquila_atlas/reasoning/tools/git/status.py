"""GitStatusTool — show working tree status (local) or repo info (GitHub)."""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._helpers import _gh_get, _gh_owner_repo, _gh_token, _resolve_repo_source, _run_git

logger = logging.getLogger("aquila.reasoning")


class GitStatusInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")


class GitStatusTool(BaseTool):
    """Show working tree status (local) or latest branch/commit info (GitHub)."""

    name: str = "git_status"
    description: str = (
        "For local repos: show staged, unstaged, and untracked files (git status). "
        "For GitHub repos: show the default branch, latest commit, and open branch list. "
        "Useful for understanding the current state of the repository."
    )
    args_schema: type[BaseModel] = GitStatusInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, repo_id: str) -> str:
        logger.debug("tool=git_status repo=%s", repo_id)
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "local":
            out, err2 = _run_git(source, ["status", "--short", "--branch"])
            if err2:
                return f"git status failed: {err2}"
            if not out.strip():
                return "Working tree is clean — no staged, unstaged, or untracked changes."
            return f"git status for '{repo_id}':\n\n{out}"

        # GitHub — no working tree; show repo summary instead
        assert isinstance(source, str)
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

        # Latest commit on default branch
        commit_data, _ = _gh_get(
            f"/repos/{owner}/{repo}/commits/{default_branch}", token
        )
        latest = ""
        if isinstance(commit_data, dict):
            sha = str(commit_data.get("sha", ""))[:7]
            info = commit_data.get("commit", {})
            msg = str(info.get("message", "")).splitlines()[0]
            author = (info.get("author") or {})
            name = str(author.get("name", ""))
            date = str(author.get("date", ""))[:10]
            latest = f"\nLatest commit on {default_branch}: {sha}  {date}  {name}  {msg}"

        # Branch list (up to 15)
        branches_data, _ = _gh_get(f"/repos/{owner}/{repo}/branches?per_page=15", token)
        branch_list = ""
        if isinstance(branches_data, list):
            names = [str(b.get("name", "")) for b in branches_data]
            branch_list = "\nBranches: " + ", ".join(names)

        return (
            f"git status for '{repo_id}' (GitHub — no working tree):\n"
            f"  Repository:    {owner}/{repo}\n"
            f"  Default branch: {default_branch}\n"
            f"  Stars: {stars}  Forks: {forks}  Open issues: {open_issues}"
            f"{latest}{branch_list}"
        )
