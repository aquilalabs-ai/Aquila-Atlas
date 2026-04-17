"""GitDiffTool — show a diff between git refs (local or GitHub)."""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._helpers import (
    _GIT_MAX_OUTPUT,
    _gh_get,
    _gh_owner_repo,
    _gh_token,
    _resolve_repo_source,
    _run_git,
)

logger = logging.getLogger("aquila.reasoning")


class GitDiffInput(BaseModel):
    repo_id: str = Field(description="Repository ID to inspect")
    ref1: str = Field(
        default="HEAD",
        description=(
            "Base git ref (commit SHA, branch, or tag). Defaults to 'HEAD'. "
            "For local repos, leave ref2 empty to diff the working tree against ref1."
        ),
    )
    ref2: str = Field(
        default="",
        description=(
            "Optional second ref to compare against ref1. "
            "For local repos: defaults to working tree. "
            "For GitHub repos: defaults to HEAD~1 when ref1 is HEAD, "
            "so the diff shows what the latest commit introduced."
        ),
    )
    file_path: str | None = Field(
        default=None,
        description="Optional: restrict the diff to a specific file (relative path).",
    )


class GitDiffTool(BaseTool):
    """Show a diff between git refs (local or GitHub)."""

    name: str = "git_diff"
    description: str = (
        "Show a git diff between two commits, branches, or tags. "
        "For local repos you can also compare against the working tree by leaving ref2 empty. "
        "For GitHub repos both refs are compared via the GitHub compare API. "
        "Works for local git repos and GitHub-hosted repos."
    )
    args_schema: type[BaseModel] = GitDiffInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(
        self,
        repo_id: str,
        ref1: str = "HEAD",
        ref2: str = "",
        file_path: str | None = None,
    ) -> str:
        logger.debug(
            "tool=git_diff repo=%s ref1=%r ref2=%r file=%r", repo_id, ref1, ref2, file_path
        )
        from aquila_atlas.knowledge.service import KnowledgeService  # noqa: PLC0415, TC001

        svc = cast("KnowledgeService", self.service)
        kind, source, err = _resolve_repo_source(svc, repo_id)
        if kind == "error":
            return err  # type: ignore[return-value]

        if kind == "local":
            args = ["diff", "--no-color"]
            if ref1:
                args.append(ref1)
            if ref2:
                args.append(ref2)
            if file_path:
                args += ["--", file_path]
            out, err2 = _run_git(source, args)
            if err2:
                return f"git diff failed: {err2}"
            if not out.strip():
                return "No differences found."
            label = f"{ref1}{'...' + ref2 if ref2 else ' (working tree)'}"
            header = f"git diff {label}"
            if file_path:
                header += f" -- {file_path}"
            return f"{header}:\n\n{out}"

        # GitHub — use compare API
        assert isinstance(source, str)
        parsed = _gh_owner_repo(source)
        if not parsed:
            return f"Could not parse GitHub URL: {source}"
        owner, repo = parsed
        token = _gh_token()

        # When ref2 is not supplied, compare ref1~1...ref1 (changes introduced by ref1)
        base = ref1 if ref1 else "HEAD"
        head = ref2 if ref2 else base
        if head == base:
            # Show what the commit at `base` introduced
            head = base
            base = f"{base}~1"

        data, err2 = _gh_get(f"/repos/{owner}/{repo}/compare/{base}...{head}", token)
        if err2:
            return f"git diff failed: {err2}"
        if not isinstance(data, dict):
            return "No diff data returned."

        files = data.get("files") or []
        if not files:
            return f"No differences between {base} and {head}."

        if file_path:
            files = [f for f in files if str(f.get("filename", "")) == file_path]
            if not files:
                return f"No diff for '{file_path}' between {base} and {head}."

        parts = [f"git diff {base}...{head} (GitHub — {len(files)} file(s) changed):\n"]
        total_chars = len(parts[0])
        for f in files:
            fname = f.get("filename", "?")
            status = f.get("status", "?")
            additions = f.get("additions", 0)
            deletions = f.get("deletions", 0)
            patch = str(f.get("patch", ""))
            entry = f"\n--- {fname}  [{status}  +{additions}/-{deletions}]\n{patch}"
            if total_chars + len(entry) > _GIT_MAX_OUTPUT:
                parts.append("\n[truncated — remaining files omitted]")
                break
            parts.append(entry)
            total_chars += len(entry)
        return "".join(parts)
