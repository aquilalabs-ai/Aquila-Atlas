"""GitLogTool — show recent commit history for a local or remote repository."""

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


class GitLogInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    branch: str | None = Field(
        default=None,
        description=(
            "Optional: branch, tag, or commit SHA to read history from. "
            "Defaults to the current HEAD (local) or default branch (remote). "
            "Example: 'develop', 'feature/auth', 'v1.2.0'."
        ),
    )
    limit: int = Field(
        default=20,
        description="Maximum number of commits to return (1-100). Default 20.",
    )
    file_path: str | None = Field(
        default=None,
        description=(
            "Optional: restrict the log to commits that touched a specific file "
            "(relative path from the repository root, e.g. 'src/main.py')."
        ),
    )


class GitLogTool(BaseTool):
    """Show recent commit history for a local or remote repository."""

    name: str = "git_log"
    description: str = (
        "Show the recent commit history (git log) for the repository. "
        "Returns commit hash, author, date, and message for each commit. "
        "Optionally filter by branch/tag and by file path. "
        "Works for local git repos and GitHub/GitLab/Gitea-hosted repos."
    )
    args_schema: type[BaseModel] = GitLogInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        branch: str | None = None,
        limit: int = 20,
        file_path: str | None = None,
    ) -> str:
        logger.debug(
            "tool=git_log repo=%s branch=%r limit=%d file=%r", repo_id, branch, limit, file_path
        )
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415, TC001

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        limit = max(1, min(limit, 100))

        # ── Local ────────────────────────────────────────────────────────────
        if kind == "local":
            args = [
                "log",
                f"-{limit}",
                "--pretty=format:%h  %ad  %an  %s",
                "--date=short",
                "--no-color",
            ]
            if branch:
                args.append(branch)
            if file_path:
                args += ["--follow", "--", file_path]
            out, err2 = _run_git(source, args)
            if err2:
                return f"git log failed: {err2}"
            if not out.strip():
                return "No commits found (the repository may have no commits yet)."
            header = f"git log for '{repo_id}'"
            if branch:
                header += f" [{branch}]"
            if file_path:
                header += f" — {file_path}"
            return f"{header}  (last {limit}):\n\n{out}"

        assert isinstance(source, str)

        # ── GitHub ───────────────────────────────────────────────────────────
        if kind == "github":
            parsed = _gh_owner_repo(source)
            if not parsed:
                return f"Could not parse GitHub URL: {source}"
            owner, repo = parsed
            qs = f"?per_page={limit}"
            if branch:
                qs += f"&sha={branch}"
            if file_path:
                qs += f"&path={file_path}"
            data, err2 = _gh_get(f"/repos/{owner}/{repo}/commits{qs}", _gh_token())
            if err2:
                return f"git log failed: {err2}"
            if not isinstance(data, list) or not data:
                return "No commits found."
            lines: list[str] = []
            for c in data:
                sha = str(c.get("sha", ""))[:7]
                info = c.get("commit", {})
                msg = str(info.get("message", "")).splitlines()[0]
                author = info.get("author") or {}
                name = str(author.get("name", ""))
                date = str(author.get("date", ""))[:10]
                lines.append(f"{sha}  {date}  {name}  {msg}")
            header = f"git log for '{repo_id}' (GitHub)"
            if branch:
                header += f" [{branch}]"
            if file_path:
                header += f" — {file_path}"
            return f"{header}  (last {limit}):\n\n" + "\n".join(lines)

        # ── GitLab ───────────────────────────────────────────────────────────
        if kind == "gitlab":
            parts = _gl_parts(source)
            if not parts:
                return (
                    f"Cannot query the GitLab API for SSH-cloned repo '{repo_id}'. "
                    "Re-ingest using an HTTPS URL to enable git tool support."
                )
            api_base, _proj_path, proj_id = parts
            token = _gl_token()
            qs = f"?per_page={limit}"
            if branch:
                qs += f"&ref_name={_up.quote(branch, safe='')}"
            if file_path:
                qs += f"&path={_up.quote(file_path, safe='')}"
            data, err2 = _gl_get(api_base, f"/projects/{proj_id}/repository/commits{qs}", token)
            if err2:
                return f"git log failed: {err2}"
            if not isinstance(data, list) or not data:
                return "No commits found."
            lines = []
            for c in data:
                sha = str(c.get("id", ""))[:7]
                msg = str(c.get("message", "")).splitlines()[0]
                name = str(c.get("author_name", ""))
                date = str(c.get("authored_date", ""))[:10]
                lines.append(f"{sha}  {date}  {name}  {msg}")
            header = f"git log for '{repo_id}' (GitLab)"
            if branch:
                header += f" [{branch}]"
            if file_path:
                header += f" — {file_path}"
            return f"{header}  (last {limit}):\n\n" + "\n".join(lines)

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
            qs = f"?limit={limit}"
            if branch:
                qs += f"&sha={_up.quote(branch, safe='')}"
            if file_path:
                qs += f"&path={_up.quote(file_path, safe='')}"
            data, err2 = _gitea_get(api_base, f"/repos/{owner}/{repo}/commits{qs}", token)
            if err2:
                return f"git log failed: {err2}"
            commits = (
                data
                if isinstance(data, list)
                else (data or {}).get("commits", [])
                if isinstance(data, dict)
                else []
            )
            if not commits:
                return "No commits found."
            lines = []
            for c in commits:
                commit_info = c.get("commit", c)
                sha = str(c.get("sha", c.get("id", "")))[:7]
                msg = str(commit_info.get("message", "")).splitlines()[0]
                author = commit_info.get("author") or {}
                name = str(author.get("name", ""))
                date = str(author.get("date", ""))[:10]
                lines.append(f"{sha}  {date}  {name}  {msg}")
            header = f"git log for '{repo_id}' (Gitea)"
            if branch:
                header += f" [{branch}]"
            if file_path:
                header += f" — {file_path}"
            return f"{header}  (last {limit}):\n\n" + "\n".join(lines)

        return f"Unsupported source kind '{kind}' for repo '{repo_id}'."
