"""Source loaders — abstract over where code comes from."""

from __future__ import annotations

import io
import re
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import httpx

from aquila_atlas.ingestion.metadata import SourceMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}

# Paths / names to ignore during traversal
_IGNORE_NAMES = {"__pycache__", ".git", ".venv", "node_modules"}
_IGNORE_SUFFIXES = {".pyc"}


def _should_ignore(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in _IGNORE_NAMES:
            return True
    suffix = Path(path).suffix
    return suffix in _IGNORE_SUFFIXES


def detect_languages(files: list[RawFile]) -> dict[str, int]:
    """Return a mapping of language name to total byte count across *files*."""
    counts: dict[str, int] = {}
    for f in files:
        suffix = Path(f.path).suffix.lower()
        lang = EXT_TO_LANG.get(suffix)
        if lang:
            counts[lang] = counts.get(lang, 0) + len(f.content)
    return counts


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawFile:
    """A single file as loaded from any source."""

    path: str  # relative path within the project (always forward-slash)
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SourceLoader(Protocol):
    """Common interface every source loader must implement."""

    def load(self) -> Iterator[RawFile]:
        """Yield all files from the source."""
        ...

    def label(self) -> str:
        """Human-readable identifier used in logs and metadata."""
        ...

    def metadata(self) -> SourceMetadata:
        """Return high-level metadata about this source."""
        ...


# ---------------------------------------------------------------------------
# GitHub loader
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
                time.sleep(2 ** attempt)
                continue
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


# ---------------------------------------------------------------------------
# Local folder loader
# ---------------------------------------------------------------------------


class LocalFolderLoader:
    """Load a project from a local directory path."""

    def __init__(self, path: str | Path, glob: str = "**/*") -> None:
        self.root = Path(path).resolve()
        self.glob = glob

    def label(self) -> str:
        return str(self.root)

    def _iter_files(self) -> Iterator[RawFile]:
        for file in self.root.glob(self.glob):
            if not file.is_file():
                continue
            relative = file.relative_to(self.root).as_posix()
            if _should_ignore(relative):
                continue
            yield RawFile(path=relative, content=file.read_bytes())

    def load(self) -> Iterator[RawFile]:
        yield from self._iter_files()

    def metadata(self) -> SourceMetadata:
        files = list(self._iter_files())
        return SourceMetadata(label=self.label(), languages=detect_languages(files))


# ---------------------------------------------------------------------------
# Zip loader
# ---------------------------------------------------------------------------


class ZipLoader:
    """Load a project from a .zip archive (path or raw bytes)."""

    def __init__(self, source: str | Path | bytes) -> None:
        self.source = source

    def label(self) -> str:
        if isinstance(self.source, bytes):
            return "<zip bytes>"
        return str(self.source)

    def _open_zip(self) -> zipfile.ZipFile:
        if isinstance(self.source, bytes):
            return zipfile.ZipFile(io.BytesIO(self.source))
        return zipfile.ZipFile(self.source)

    def _iter_files(self) -> Iterator[RawFile]:
        with self._open_zip() as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Strip the top-level folder that most zip exports include
                parts = info.filename.split("/", 1)
                relative = parts[1] if len(parts) == 2 else parts[0]
                if not relative or _should_ignore(relative):
                    continue
                yield RawFile(path=relative, content=zf.read(info.filename))

    def load(self) -> Iterator[RawFile]:
        yield from self._iter_files()

    def metadata(self) -> SourceMetadata:
        return SourceMetadata(label=self.label())
