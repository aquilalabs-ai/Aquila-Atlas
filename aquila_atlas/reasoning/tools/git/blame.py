"""GitBlameTool — show per-line commit attribution for a file."""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._helpers import _resolve_repo_source, _run_git

logger = logging.getLogger("aquila.reasoning")


class GitBlameInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    file_path: str = Field(
        description="File to blame (relative path from the repository root, e.g. 'src/main.py')."
    )
    start_line: int | None = Field(
        default=None,
        description="Optional: first line of the range to blame (1-based).",
    )
    end_line: int | None = Field(
        default=None,
        description="Optional: last line of the range to blame (inclusive, 1-based).",
    )


class GitBlameTool(BaseTool):
    """Show per-line commit attribution (git blame) for a file."""

    name: str = "git_blame"
    description: str = (
        "Show who last modified each line of a file and in which commit (git blame). "
        "Optionally restrict to a line range. Useful for understanding the history of a "
        "specific piece of code or tracking down when a bug was introduced. "
        "Works for local git repos. GitHub repos are not supported (GitHub REST API "
        "does not expose blame; use git_log with a file_path filter instead)."
    )
    args_schema: type[BaseModel] = GitBlameInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        logger.debug(
            "tool=git_blame repo=%s file=%r lines=%s-%s",
            repo_id,
            file_path,
            start_line,
            end_line,
        )
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415, TC001

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "github":
            return (
                f"git blame is not available for GitHub-hosted repositories via the REST API. "
                f"Use git_log with file_path='{file_path}' to see which commits touched that file, "
                "then use git_diff to inspect a specific commit's changes."
            )

        args = ["blame", "--no-color", "-w"]
        if start_line is not None and end_line is not None:
            args += [f"-L{start_line},{end_line}"]
        elif start_line is not None:
            args += [f"-L{start_line},+50"]  # default 50 lines from start
        args.append(file_path)

        out, err2 = _run_git(source, args)
        if err2:
            return f"git blame failed: {err2}"
        if not out.strip():
            return f"No blame output for '{file_path}' — the file may not be tracked by git."

        header = f"git blame for '{file_path}'"
        if start_line:
            header += f" (lines {start_line}–{end_line or '…'})"
        return f"{header}:\n\n{out}"
