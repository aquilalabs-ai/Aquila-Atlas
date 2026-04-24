"""GitDiffTool — show a diff between git refs (local or remote)."""

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
            "For remote repos: defaults to HEAD~1 when ref1 is HEAD, "
            "so the diff shows what the latest commit introduced."
        ),
    )
    file_path: str | None = Field(
        default=None,
        description="Optional: restrict the diff to a specific file (relative path).",
    )


class GitDiffTool(BaseTool):
    """Show a diff between git refs (local or remote)."""

    name: str = "git_diff"
    description: str = (
        "Show a git diff between two commits, branches, or tags. "
        "For local repos you can also compare against the working tree by leaving ref2 empty. "
        "For remote repos both refs are compared via the provider compare API. "
        "Works for local git repos and GitHub/GitLab/Gitea-hosted repos."
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

        # ── Local ────────────────────────────────────────────────────────────
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

        assert isinstance(source, str)

        # ── GitHub ───────────────────────────────────────────────────────────
        if kind == "github":
            parsed = _gh_owner_repo(source)
            if not parsed:
                return f"Could not parse GitHub URL: {source}"
            owner, repo = parsed
            token = _gh_token()
            base = ref1 if ref1 else "HEAD"
            head = ref2 if ref2 else base
            if head == base:
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
            parts: list[str] = [
                f"git diff {base}...{head} (GitHub — {len(files)} file(s) changed):\n"
            ]
            total = len(parts[0])
            for f in files:
                fname = f.get("filename", "?")
                status = f.get("status", "?")
                additions = f.get("additions", 0)
                deletions = f.get("deletions", 0)
                patch = str(f.get("patch", ""))
                entry = f"\n--- {fname}  [{status}  +{additions}/-{deletions}]\n{patch}"
                if total + len(entry) > _GIT_MAX_OUTPUT:
                    parts.append("\n[truncated — remaining files omitted]")
                    break
                parts.append(entry)
                total += len(entry)
            return "".join(parts)

        # ── GitLab ───────────────────────────────────────────────────────────
        if kind == "gitlab":
            gl = _gl_parts(source)
            if not gl:
                return (
                    f"Cannot query the GitLab API for SSH-cloned repo '{repo_id}'. "
                    "Re-ingest using an HTTPS URL to enable git tool support."
                )
            api_base, _proj_path, proj_id = gl
            token = _gl_token()
            base = ref1 if ref1 else "HEAD"
            head = ref2 if ref2 else base
            if head == base:
                head = base
                base = f"{base}~1"
            import urllib.parse as _up  # noqa: PLC0415

            data, err2 = _gl_get(
                api_base,
                f"/projects/{proj_id}/repository/compare"
                f"?from={_up.quote(base, safe='')}&to={_up.quote(head, safe='')}",
                token,
            )
            if err2:
                return f"git diff failed: {err2}"
            if not isinstance(data, dict):
                return "No diff data returned."
            diffs = data.get("diffs") or []
            if not diffs:
                return f"No differences between {base} and {head}."
            if file_path:
                diffs = [
                    d for d in diffs if str(d.get("new_path") or d.get("old_path")) == file_path
                ]
                if not diffs:
                    return f"No diff for '{file_path}' between {base} and {head}."
            parts = [f"git diff {base}...{head} (GitLab — {len(diffs)} file(s) changed):\n"]
            total = len(parts[0])
            for d in diffs:
                fname = str(d.get("new_path") or d.get("old_path") or "?")
                renamed = d.get("renamed_file", False)
                deleted = d.get("deleted_file", False)
                new_file = d.get("new_file", False)
                status = (
                    "renamed"
                    if renamed
                    else "deleted"
                    if deleted
                    else "added"
                    if new_file
                    else "modified"
                )
                diff_text = str(d.get("diff", ""))
                entry = f"\n--- {fname}  [{status}]\n{diff_text}"
                if total + len(entry) > _GIT_MAX_OUTPUT:
                    parts.append("\n[truncated — remaining files omitted]")
                    break
                parts.append(entry)
                total += len(entry)
            return "".join(parts)

        # ── Gitea / Forgejo ──────────────────────────────────────────────────
        if kind == "gitea":
            gt = _gitea_parts(source)
            if not gt:
                return (
                    f"Cannot query the Gitea API for SSH-cloned repo '{repo_id}'. "
                    "Re-ingest using an HTTPS URL to enable git tool support."
                )
            api_base, owner, repo = gt
            token = _gitea_token()
            base = ref1 if ref1 else "HEAD"
            head = ref2 if ref2 else base
            import urllib.parse as _up2  # noqa: PLC0415

            data, err2 = _gitea_get(
                api_base,
                f"/repos/{owner}/{repo}/compare/{_up2.quote(base, safe='')}...{_up2.quote(head, safe='')}",
                token,
            )
            if err2:
                return f"git diff failed: {err2}"
            # Gitea compare returns a list of commit diffs; summarise file list
            if not isinstance(data, dict):
                return "No diff data returned."
            files = data.get("files") or []
            if not files:
                return f"No differences between {base} and {head}."
            if file_path:
                files = [f for f in files if str(f.get("filename", "")) == file_path]
                if not files:
                    return f"No diff for '{file_path}' between {base} and {head}."
            parts = [f"git diff {base}...{head} (Gitea — {len(files)} file(s) changed):\n"]
            total = len(parts[0])
            for f in files:
                fname = str(f.get("filename", "?"))
                status = str(f.get("status", "?"))
                adds = f.get("additions", 0)
                dels = f.get("deletions", 0)
                patch = str(f.get("patch", ""))
                entry = f"\n--- {fname}  [{status}  +{adds}/-{dels}]\n{patch}"
                if total + len(entry) > _GIT_MAX_OUTPUT:
                    parts.append("\n[truncated — remaining files omitted]")
                    break
                parts.append(entry)
                total += len(entry)
            return "".join(parts)

        return f"Unsupported source kind '{kind}' for repo '{repo_id}'."
