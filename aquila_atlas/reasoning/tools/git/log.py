"""GitLogTool — show recent commit history for a local or GitHub-ingested repository."""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._helpers import _gh_get, _gh_owner_repo, _gh_token, _resolve_repo_source, _run_git

logger = logging.getLogger("aquila.reasoning")


class GitLogInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    branch: str | None = Field(
        default=None,
        description=(
            "Optional: branch, tag, or commit SHA to read history from. "
            "Defaults to the current HEAD (local) or default branch (GitHub). "
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
    """Show recent commit history for a local or GitHub-ingested repository."""

    name: str = "git_log"
    description: str = (
        "Show the recent commit history (git log) for the repository. "
        "Returns commit hash, author, date, and message for each commit. "
        "Optionally filter by branch/tag and by file path. "
        "Works for local git repos and GitHub-hosted repos."
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
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        limit = max(1, min(limit, 100))

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

        # GitHub
        assert isinstance(source, str)
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
