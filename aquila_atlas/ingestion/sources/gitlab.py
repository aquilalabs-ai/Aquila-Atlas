"""GitLab repository source loader.

Supports:
  - https://gitlab.com/owner/repo
  - https://gitlab.com/group/subgroup/repo
  - Self-hosted:  https://gitlab.example.com/owner/repo

The ``base_url`` parameter defaults to ``https://gitlab.com`` but can be set
to any self-hosted GitLab instance.  Authentication uses a GitLab Personal
Access Token (PAT) or project access token passed as ``token``.
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

_DEFAULT_BASE = "https://gitlab.com"


class GitLabLoader:
    """Load a repository from a GitLab instance via the REST API.

    Args:
        url: Full GitLab project URL, e.g.
            ``https://gitlab.com/owner/repo`` or
            ``https://gitlab.example.com/group/subgroup/repo``.
        token: GitLab Personal Access Token or project access token.
            Required for private repositories.
        branch: Branch or tag to ingest.  Defaults to the project's
            default branch when empty.
    """

    def __init__(self, url: str, token: str = "", branch: str = "") -> None:
        self.url = url.rstrip("/")
        self.token = token

        # Split the URL into <base>/<namespace>/<project>
        # The base URL is everything up to (but not including) the path.
        parsed = urllib.parse.urlparse(self.url)
        path = parsed.path.strip("/").removesuffix(".git")
        parts = path.split("/")
        if len(parts) < 2:
            raise ValueError(
                f"Cannot parse GitLab URL {url!r}. "
                "Expected format: https://<host>/[group/]owner/repo"
            )
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._api = f"{self.base_url}/api/v4"
        # Namespace is everything except the last segment
        self.namespace = "/".join(parts[:-1])
        self.project_name = parts[-1]
        self._project_path = path  # group/owner/repo — used as project ID
        self._project_id_encoded = urllib.parse.quote(path, safe="")
        self.branch = branch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["PRIVATE-TOKEN"] = self.token
        return h

    def _get_json(self, client: httpx.Client, path: str, *, retries: int = 3) -> object:
        for attempt in range(retries):
            resp = client.get(f"{self._api}{path}", headers=self._headers())
            if resp.status_code in {500, 502, 503, 504} and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if resp.status_code == 401:
                raise ValueError(
                    f"GitLab authentication failed — check your access token. URL: {self.url}"
                ) from None
            if resp.status_code == 403:
                raise ValueError(
                    "GitLab access forbidden — token may lack read_repository scope. "
                    f"URL: {self.url}"
                ) from None
            if resp.status_code == 404:
                msg = (
                    f"GitLab project not found: {self.url!r}. "
                    "Check the URL and ensure the token has access to private repos."
                    if self.token
                    else f"GitLab project not found: {self.url!r}. "
                    "Private repos require a Personal Access Token."
                )
                raise ValueError(msg) from None
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def _project(self, client: httpx.Client) -> dict[str, object]:
        data = self._get_json(client, f"/projects/{self._project_id_encoded}")
        assert isinstance(data, dict)
        return data

    def _resolve_branch(self, client: httpx.Client) -> str:
        if self.branch:
            return self.branch
        proj = self._project(client)
        return str(proj.get("default_branch", "main"))

    def _latest_sha(self, client: httpx.Client, branch: str) -> str:
        data = self._get_json(
            client,
            f"/projects/{self._project_id_encoded}/repository/commits/{urllib.parse.quote(branch, safe='')}",
        )
        assert isinstance(data, dict)
        return str(data["id"])

    def _download_tarball(self, client: httpx.Client, sha: str) -> bytes:
        resp = client.get(
            f"{self._api}/projects/{self._project_id_encoded}/repository/archive.tar.gz",
            params={"sha": sha},
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
                    f"/projects/{self._project_id_encoded}/repository/compare"
                    f"?from={old_sha}&to={new_sha}",
                )
            assert isinstance(data, dict)
            diffs = data.get("diffs", [])
            assert isinstance(diffs, list)
            paths: list[str] = []
            for d in diffs:
                if isinstance(d, dict):
                    p = str(d.get("new_path") or d.get("old_path") or "")
                    if p and not _should_ignore(p):
                        paths.append(p)
            return paths
        except Exception:  # noqa: BLE001
            return []

    def metadata(self) -> SourceMetadata:
        with httpx.Client(timeout=60) as client:
            branch = self._resolve_branch(client)
            sha = self._latest_sha(client, branch)
            proj = self._project(client)
        languages: dict[str, int] = {}
        lang = proj.get("predominant_language")
        if lang:
            languages[str(lang)] = 1
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
                # GitLab archives: <project>-<branch>-<sha>/<relative_path>
                parts = member.name.split("/", 1)
                relative = parts[1] if len(parts) == 2 else parts[0]
                if not relative or _should_ignore(relative):
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                yield RawFile(path=relative, content=f.read())


def _parse_gitlab_url(url: str) -> tuple[str, str]:
    """Return (namespace, project_name) from a GitLab URL. Used by tests."""
    parsed = urllib.parse.urlparse(url.rstrip("/"))
    path = parsed.path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse GitLab URL: {url!r}")
    return "/".join(parts[:-1]), parts[-1]
