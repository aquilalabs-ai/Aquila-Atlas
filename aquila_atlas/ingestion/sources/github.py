"""GitHub repository source loader."""

from __future__ import annotations

import io
import re
import tarfile
import time
from typing import TYPE_CHECKING

import httpx

from aquila_atlas.ingestion.metadata import SourceMetadata
from aquila_atlas.ingestion.sources._common import RawFile, _should_ignore

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"
_GH_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:/tree/(?P<branch>[^/].*))?/?$"
)


class GitHubLoader:
    """Load a repository from a GitHub URL.

    Supports:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/<branch>
    """

    def __init__(
        self,
        url: str,
        token: str = "",
        branch: str = "",
        since_sha: str | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.since_sha = since_sha

        m = _GH_URL_RE.match(self.url)
        if not m:
            raise ValueError(f"Cannot parse GitHub URL: {url!r}")
        self.owner: str = m.group("owner")
        self.repo: str = m.group("repo").removesuffix(".git")
        # Branch from URL takes precedence over kwarg; fall back to "HEAD"
        url_branch = m.group("branch")
        self.branch: str = url_branch or branch or "HEAD"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get_json(self, client: httpx.Client, path: str, *, retries: int = 3) -> object:
        for attempt in range(retries):
            resp = client.get(f"{_GH_API}{path}", headers=self._headers())
            if resp.status_code in {500, 502, 503, 504} and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if resp.status_code == 404:
                if self.token:
                    raise ValueError(
                        f"Repository not found or access denied. "
                        f"Check that the repository exists and your GitHub token has access to private repositories. "
                        f"URL: {self.url}"
                    ) from None
                else:
                    raise ValueError(
                        f"Repository not found. If this is a private repository, "
                        f"provide a GitHub token with 'repo' scope. URL: {self.url}"
                    ) from None
            if resp.status_code == 401:
                raise ValueError(
                    f"GitHub token authentication failed. "
                    f"Check that your token is valid and has not expired. URL: {self.url}"
                ) from None
            if resp.status_code == 403:
                if "rate limit" in resp.text.lower():
                    raise ValueError(
                        f"GitHub API rate limit exceeded. "
                        f"Try again later or provide a GitHub token. URL: {self.url}"
                    ) from None
                else:
                    raise ValueError(
                        f"GitHub API access forbidden. "
                        f"Check your token permissions. URL: {self.url}"
                    ) from None
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()  # unreachable, satisfies type checker
        return resp.json()

    def _resolve_branch(self, client: httpx.Client) -> str:
        """Return the effective branch name (resolves 'HEAD' to default branch)."""
        if self.branch != "HEAD":
            return self.branch
        data = self._get_json(client, f"/repos/{self.owner}/{self.repo}")
        assert isinstance(data, dict)
        return str(data["default_branch"])

    def _latest_sha(self, client: httpx.Client, branch: str) -> str:
        data = self._get_json(client, f"/repos/{self.owner}/{self.repo}/commits/{branch}")
        assert isinstance(data, dict)
        return str(data["sha"])

    def _languages(self, client: httpx.Client) -> dict[str, int]:
        data = self._get_json(client, f"/repos/{self.owner}/{self.repo}/languages")
        assert isinstance(data, dict)
        return {str(k): int(v) for k, v in data.items()}

    def _download_tarball(self, client: httpx.Client, branch: str) -> bytes:
        resp = client.get(
            f"{_GH_API}/repos/{self.owner}/{self.repo}/tarball/{branch}",
            headers=self._headers(),
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def label(self) -> str:
        return self.url

    def head_sha(self) -> str | None:
        """Return the current HEAD commit SHA for this GitHub repo, or None."""
        try:
            with httpx.Client() as client:
                branch = self._resolve_branch(client)
                return self._latest_sha(client, branch)
        except Exception:  # noqa: BLE001
            return None

    def diff_files(self, old_sha: str, new_sha: str) -> list[str]:
        """Return file paths changed between *old_sha* and *new_sha* via the GitHub compare API.

        Includes added, modified, renamed, and deleted files.
        """
        try:
            with httpx.Client() as client:
                data = self._get_json(
                    client,
                    f"/repos/{self.owner}/{self.repo}/compare/{old_sha}...{new_sha}",
                )
            assert isinstance(data, dict)
            files = data.get("files", [])
            assert isinstance(files, list)
            paths = [str(f["filename"]) for f in files if isinstance(f, dict) and "filename" in f]
            return [p for p in paths if not _should_ignore(p)]
        except Exception:  # noqa: BLE001
            return []

    def metadata(self) -> SourceMetadata:
        with httpx.Client() as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)
            langs = self._languages(client)
        return SourceMetadata(
            label=self.label(),
            commit_sha=sha,
            branch=branch,
            languages=langs,
        )

    def load(self) -> Iterator[RawFile]:
        with httpx.Client() as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)

            if self.since_sha and sha == self.since_sha:
                return

            tarball = self._download_tarball(client, branch)

        yield from self._iter_tarball(tarball)

    def load_paths(self, file_paths: list[str]) -> Iterator[RawFile]:
        """Yield only the files whose relative path is in *file_paths*."""
        wanted = set(file_paths)
        with httpx.Client() as client:
            branch = self._resolve_branch(client)
            tarball = self._download_tarball(client, branch)
        for raw in self._iter_tarball(tarball):
            if raw.path in wanted:
                yield raw

    def _iter_tarball(self, tarball: bytes) -> Iterator[RawFile]:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                # Strip top-level GitHub wrapper dir (owner-repo-sha/)
                parts = member.name.split("/", 1)
                relative = parts[1] if len(parts) == 2 else parts[0]
                if not relative or _should_ignore(relative):
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                yield RawFile(path=relative, content=f.read())