"""Source loaders — abstract over where code comes from."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator, Protocol


@dataclass(frozen=True)
class RawFile:
    """A single file as loaded from any source."""

    path: str   # relative path within the project (always forward-slash)
    content: bytes


class SourceLoader(Protocol):
    """Common interface every source loader must implement."""

    def load(self) -> Iterator[RawFile]:
        """Yield all files from the source."""
        ...

    def label(self) -> str:
        """Human-readable identifier used in logs and metadata."""
        ...


class GitHubLoader:
    """Load a repository from a GitHub URL.

    Supports:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/<branch>
    """

    def __init__(self, url: str, token: str = "", branch: str = "HEAD") -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.branch = branch

    def label(self) -> str:
        return self.url

    def load(self) -> Iterator[RawFile]:
        # TODO (Phase 1): implement via GitHub Contents API / git clone
        raise NotImplementedError


class LocalFolderLoader:
    """Load a project from a local directory path."""

    def __init__(self, path: str | Path, glob: str = "**/*") -> None:
        self.root = Path(path).resolve()
        self.glob = glob

    def label(self) -> str:
        return str(self.root)

    def load(self) -> Iterator[RawFile]:
        # TODO (Phase 1): add .gitignore / .aquilaignore filtering
        for file in self.root.glob(self.glob):
            if file.is_file():
                relative = file.relative_to(self.root).as_posix()
                yield RawFile(path=relative, content=file.read_bytes())


class ZipLoader:
    """Load a project from a .zip archive (path or raw bytes)."""

    def __init__(self, source: str | Path | bytes) -> None:
        self.source = source

    def label(self) -> str:
        if isinstance(self.source, bytes):
            return "<zip bytes>"
        return str(self.source)

    def load(self) -> Iterator[RawFile]:
        if isinstance(self.source, bytes):
            import io
            zf = zipfile.ZipFile(io.BytesIO(self.source))
        else:
            zf = zipfile.ZipFile(self.source)

        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Strip the top-level folder that most zip exports include
                parts = info.filename.split("/", 1)
                relative = parts[1] if len(parts) == 2 else parts[0]
                yield RawFile(path=relative, content=zf.read(info.filename))
