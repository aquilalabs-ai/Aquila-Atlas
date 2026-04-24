"""Universal git-clone source loader.

Clones any URL that ``git clone`` accepts — HTTPS, SSH, or ``file://`` — into
a temporary directory, reads the source files, then cleans up automatically.

This covers providers that don't have a dedicated REST loader:

- Bitbucket Cloud / Server
- Azure DevOps (formerly VSTS)
- AWS CodeCommit
- Self-hosted Gitolite, Gogs, or any plain ``git`` server
- Company internal SSH remotes (``git@git.corp.com:team/repo.git``)

Token injection for HTTPS URLs
-------------------------------
Pass ``token`` for services that accept a bearer token in the URL::

    # GitLab
    GitCloneLoader("https://gitlab.example.com/group/repo.git", token="glpat-...")
    # GitHub
    GitCloneLoader("https://github.com/owner/repo.git", token="ghp_...")
    # Gitea
    GitCloneLoader("https://gitea.example.com/owner/repo.git", token="...")
    # Bitbucket (app password: user:password)
    GitCloneLoader("https://user:app-password@bitbucket.org/owner/repo.git")

For SSH URLs the token is ignored; authentication is handled by the SSH agent
or ``~/.ssh/config`` on the server running Aquila-Atlas.

Resync support
--------------
``diff_files`` performs a fresh shallow clone and runs ``git diff --name-only``
between the two SHAs.  Because this involves a network round-trip, it is
slower than the local-folder approach but works for any remote.
"""

from __future__ import annotations

import subprocess
import tempfile
import urllib.parse
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import SourceMetadata
from aquila_atlas.ingestion.sources._common import RawFile, _should_ignore, detect_languages
from aquila_atlas.ingestion.sources.local import LocalFolderLoader

if TYPE_CHECKING:
    from collections.abc import Iterator

_GIT_TIMEOUT_CLONE = 300  # seconds
_GIT_TIMEOUT_CMD = 30


class GitCloneLoader:
    """Clone any git repository and load its source files.

    Args:
        url: Any URL accepted by ``git clone`` (HTTPS, SSH, ``file://``).
        token: Optional bearer token injected into HTTPS URLs.  Ignored for
            SSH or ``file://`` URLs.
        branch: Branch, tag, or commit to check out.  Defaults to the remote
            HEAD when empty.
    """

    def __init__(self, url: str, token: str = "", branch: str = "") -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.branch = branch

    def _clone_url(self) -> str:
        """Return the URL with an embedded token when applicable."""
        if not self.token:
            return self.url
        parsed = urllib.parse.urlparse(self.url)
        # Only inject for http(s) — SSH and file:// don't use token auth
        if parsed.scheme not in ("http", "https"):
            return self.url
        # Embed as oauth2:<token>@host (works for GitLab, GitHub, Gitea, Bitbucket)
        netloc_with_token = f"oauth2:{self.token}@{parsed.hostname}"
        if parsed.port:
            netloc_with_token += f":{parsed.port}"
        return parsed._replace(netloc=netloc_with_token).geturl()

    def _run_git(
        self, args: list[str], cwd: str | None = None, timeout: int = _GIT_TIMEOUT_CMD
    ) -> str:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.stdout.strip()

    def _clone_into(self, tmpdir: str, depth: int | None = 1) -> None:
        clone_args = ["clone", "--quiet"]
        if depth is not None:
            clone_args += ["--depth", str(depth)]
        if self.branch:
            clone_args += ["--branch", self.branch]
        clone_args += ["--", self._clone_url(), tmpdir]
        subprocess.run(
            ["git", *clone_args],
            capture_output=True,
            check=True,
            timeout=_GIT_TIMEOUT_CLONE,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def label(self) -> str:
        return self.url

    def head_sha(self) -> str | None:
        """Clone the repo (shallow) and return the HEAD commit SHA."""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                self._clone_into(tmpdir)
                return self._run_git(["rev-parse", "HEAD"], cwd=tmpdir)
        except Exception:  # noqa: BLE001
            return None

    def diff_files(self, old_sha: str, new_sha: str) -> list[str]:
        """Return file paths changed between *old_sha* and *new_sha*.

        Performs a fresh clone without ``--depth`` to ensure both SHAs are
        reachable, then runs ``git diff --name-only``.
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Full clone so both SHAs are in history
                self._clone_into(tmpdir, depth=None)
                output = self._run_git(
                    ["diff", "--name-only", old_sha, new_sha],
                    cwd=tmpdir,
                    timeout=60,
                )
            paths = [p.strip() for p in output.splitlines() if p.strip()]
            return [p for p in paths if not _should_ignore(p)]
        except Exception:  # noqa: BLE001
            return []

    def metadata(self) -> SourceMetadata:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._clone_into(tmpdir)
            sha = self._run_git(["rev-parse", "HEAD"], cwd=tmpdir)
            try:
                branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=tmpdir)
            except Exception:  # noqa: BLE001
                branch = self.branch or "HEAD"
            files = list(LocalFolderLoader(tmpdir)._iter_files())
        return SourceMetadata(
            label=self.label(),
            commit_sha=sha,
            branch=branch,
            languages=detect_languages(files),
        )

    def load(self) -> Iterator[RawFile]:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._clone_into(tmpdir)
            yield from LocalFolderLoader(tmpdir)._iter_files()

    def load_paths(self, file_paths: list[str]) -> Iterator[RawFile]:
        wanted = set(file_paths)
        with tempfile.TemporaryDirectory() as tmpdir:
            self._clone_into(tmpdir)
            for raw in LocalFolderLoader(tmpdir)._iter_files():
                if raw.path in wanted:
                    yield raw
