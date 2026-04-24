"""Gitea / Forgejo repository source loader.

Supports any self-hosted Gitea or Forgejo instance.  Both platforms share
an identical REST API so the same loader handles both.

Usage::

    loader = GiteaLoader(
        url="https://gitea.example.com/owner/repo",
        token="your-access-token",
    )

The ``url`` must point to the repository root
(``https://<host>/[org/]owner/repo``).  Authentication uses a Gitea personal
access token or API key passed as ``token``.
"""

from __future__ import annotations

import io
import tarfile
import time
import urllib.parse
from typing import TYPE_CHECKING

import httpx

from aquila_atlas.ingestion.metadata import SourceMetadata
from aquila_atlas.ingestion.sources._common import RawFile, _should_ignore

if TYPE_CHECKING:
    from collections.abc import Iterator


class GiteaLoader:
    """Load a repository from a Gitea or Forgejo instance via its REST API.

    Args:
        url: Full repository URL, e.g.
            ``https://gitea.example.com/owner/repo``.
        token: Gitea personal access token.  Required for private repos.
        branch: Branch or tag to ingest.  Defaults to the repo's default
            branch when empty.
    """

    def __init__(self, url: str, token: str = "", branch: str = "") -> None:
        self.url = url.rstrip("/").removesuffix(".git")
        self.token = token

        parsed = urllib.parse.urlparse(self.url)
        path = parsed.path.strip("/")
        parts = path.split("/")
        if len(parts) < 2:
            raise ValueError(
                f"Cannot parse Gitea URL {url!r}. Expected format: https://<host>/owner/repo"
            )
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._api = f"{self.base_url}/api/v1"
        self.owner = parts[0]
        self.repo = parts[1]
        self.branch = branch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"token {self.token}"}
        return {}

    def _get_json(self, client: httpx.Client, path: str, *, retries: int = 3) -> object:
        for attempt in range(retries):
            resp = client.get(f"{self._api}{path}", headers=self._headers())
            if resp.status_code in {500, 502, 503, 504} and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if resp.status_code == 401:
                raise ValueError(
                    f"Gitea authentication failed — check your access token. URL: {self.url}"
                ) from None
            if resp.status_code == 404:
                msg = (
                    f"Gitea repository not found: {self.url!r}. "
                    "Check the URL and ensure the token has access."
                    if self.token
                    else f"Gitea repository not found: {self.url!r}. "
                    "Private repos require an access token."
                )
                raise ValueError(msg) from None
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def _repo_info(self, client: httpx.Client) -> dict[str, object]:
        data = self._get_json(client, f"/repos/{self.owner}/{self.repo}")
        assert isinstance(data, dict)
        return data

    def _resolve_branch(self, client: httpx.Client) -> str:
        if self.branch:
            return self.branch
        info = self._repo_info(client)
        return str(info.get("default_branch", "main"))

    def _latest_sha(self, client: httpx.Client, branch: str) -> str:
        data = self._get_json(
            client,
            f"/repos/{self.owner}/{self.repo}/branches/{urllib.parse.quote(branch, safe='')}",
        )
        assert isinstance(data, dict)
        commit = data.get("commit", {})
        assert isinstance(commit, dict)
        return str(commit["id"])

    def _download_tarball(self, client: httpx.Client, sha: str) -> bytes:
        resp = client.get(
            f"{self._api}/repos/{self.owner}/{self.repo}/archive/{sha}.tar.gz",
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
        try:
            with httpx.Client(timeout=30) as client:
                branch = self._resolve_branch(client)
                return self._latest_sha(client, branch)
        except Exception:  # noqa: BLE001
            return None

    def diff_files(self, old_sha: str, new_sha: str) -> list[str]:
        """Return file paths changed between *old_sha* and *new_sha*."""
        try:
            with httpx.Client(timeout=30) as client:
                data = self._get_json(
                    client,
                    f"/repos/{self.owner}/{self.repo}/compare/{old_sha}...{new_sha}",
                )
            assert isinstance(data, dict)
            files = data.get("files", [])
            assert isinstance(files, list)
            paths: list[str] = []
            for f in files:
                if isinstance(f, dict):
                    p = str(f.get("filename") or "")
                    if p and not _should_ignore(p):
                        paths.append(p)
            return paths
        except Exception:  # noqa: BLE001
            return []

    def metadata(self) -> SourceMetadata:
        with httpx.Client(timeout=60) as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)
            info = self._repo_info(client)
        lang = info.get("language")
        languages = {str(lang): 1} if lang else {}
        return SourceMetadata(
            label=self.label(),
            commit_sha=sha,
            branch=branch,
            languages=languages,
        )

    def load(self) -> Iterator[RawFile]:
        with httpx.Client(timeout=300) as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)
            tarball = self._download_tarball(client, sha)
        yield from self._iter_tarball(tarball)

    def load_paths(self, file_paths: list[str]) -> Iterator[RawFile]:
        wanted = set(file_paths)
        with httpx.Client(timeout=300) as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)
            tarball = self._download_tarball(client, sha)
        for raw in self._iter_tarball(tarball):
            if raw.path in wanted:
                yield raw

    def _iter_tarball(self, tarball: bytes) -> Iterator[RawFile]:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                # Gitea archives: <repo>-<sha>/<relative_path>
                parts = member.name.split("/", 1)
                relative = parts[1] if len(parts) == 2 else parts[0]
                if not relative or _should_ignore(relative):
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                yield RawFile(path=relative, content=f.read())
