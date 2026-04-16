"""Shared helpers for git tools (local subprocess + GitHub REST API)."""

from __future__ import annotations

import re as _re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService

_GIT_MAX_OUTPUT = 6000  # chars — truncate long output to keep context lean

_GH_REPO_RE = _re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:/tree/[^/].*)?/?$"
)


def _resolve_repo_source(
    svc: KnowledgeService, repo_id: str
) -> tuple[str, Any, str | None]:
    """Resolve *repo_id* to its ingested source.

    Returns one of:
    - ``("local", Path, None)``   — local directory that is a git repo
    - ``("github", url, None)``   — GitHub-hosted repo (URL string)
    - ``("error", None, message)``— unusable source with a human-readable reason
    """
    try:
        rows = cast("KnowledgeService", svc).graph.cypher_read(
            "MATCH (r:Repository {id: $repo_id}) RETURN r.label AS label",
            params={"repo_id": repo_id},
        )
    except Exception as exc:  # noqa: BLE001
        return "error", None, f"Could not look up repo '{repo_id}': {exc}"

    if not rows:
        return "error", None, (
            f"Repository '{repo_id}' not found. Has it been ingested yet? "
            "Run 'uv run aquila repos' to list available repositories."
        )

    label = str(rows[0].get("label") or "")
    if not label:
        return "error", None, f"Repository '{repo_id}' has no source path recorded."

    # GitHub URL
    if _GH_REPO_RE.match(label.rstrip("/")):
        return "github", label, None

    # Other remote URLs (GitLab, Bitbucket, raw git…) — no API support yet
    if label.startswith(("https://", "http://", "git@", "ssh://")):
        return "error", None, (
            f"Repository '{repo_id}' was ingested from a remote URL ({label}). "
            "Only GitHub and local git repositories are supported by the git tools."
        )

    # Local path
    path = Path(label)
    if not path.exists():
        return "error", None, (
            f"Source directory '{label}' no longer exists on disk. "
            "The repository may have been moved or deleted since ingestion."
        )

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return "error", None, "git is not installed or not found in PATH."
    except subprocess.TimeoutExpired:
        return "error", None, "git command timed out while detecting repository root."

    if result.returncode != 0:
        return "error", None, (
            f"'{label}' is not a git repository (no .git found). "
            "Git tools require the source folder to be initialised with git."
        )

    return "local", path, None


def _run_git(path: Path, args: list[str], timeout: int = 30) -> tuple[str, str | None]:
    """Run a git command in *path*.  Returns ``(stdout, None)`` or ``('', error)``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return "", result.stderr.strip() or f"git exited with code {result.returncode}"
        out = result.stdout
        if len(out) > _GIT_MAX_OUTPUT:
            out = out[:_GIT_MAX_OUTPUT] + f"\n\n[truncated — output exceeds {_GIT_MAX_OUTPUT} chars]"
        return out, None
    except subprocess.TimeoutExpired:
        return "", "git command timed out."
    except FileNotFoundError:
        return "", "git is not installed or not found in PATH."


def _gh_headers(token: str = "") -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _gh_get(path: str, token: str = "") -> tuple[Any, str | None]:
    """GET a GitHub API path.  Returns ``(data, None)`` or ``(None, error)``."""
    import httpx  # noqa: PLC0415

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"https://api.github.com{path}", headers=_gh_headers(token)
            )
            if resp.status_code == 404:
                hint = (
                    " If this is a private repository, set GITHUB_TOKEN in .env with"
                    " a token that has the 'repo' scope."
                    if not token
                    else " Verify the repository exists and your token has 'repo' scope access."
                )
                return None, f"GitHub: resource not found.{hint}"
            if resp.status_code == 401:
                return None, (
                    "GitHub: authentication failed — your GITHUB_TOKEN is invalid or expired."
                    " Generate a new token at https://github.com/settings/tokens"
                    " with the 'repo' scope."
                )
            if resp.status_code == 403:
                if "rate limit" in resp.text.lower():
                    return None, (
                        "GitHub: API rate limit exceeded."
                        " Set GITHUB_TOKEN in .env to get a higher rate limit (5000 req/h)."
                    )
                return None, (
                    "GitHub: access denied — your token lacks the required 'repo' scope"
                    " for this private repository."
                )
            resp.raise_for_status()
            return resp.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"GitHub API request failed: {exc}"


def _gh_owner_repo(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a GitHub URL, or return ``None``."""
    m = _GH_REPO_RE.match(url.rstrip("/"))
    if not m:
        return None
    return m.group("owner"), m.group("repo").removesuffix(".git")


def _gh_token() -> str:
    """Return the GitHub token from settings (empty string if not configured)."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    return get_settings().github_token
