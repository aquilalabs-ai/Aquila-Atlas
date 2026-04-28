"""Local filesystem source loader."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import SourceMetadata
from aquila_atlas.ingestion.sources._common import RawFile, _should_ignore, detect_languages

if TYPE_CHECKING:
    from collections.abc import Iterator


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

    def load_paths(self, file_paths: list[str]) -> Iterator[RawFile]:
        """Yield only the files whose relative path is in *file_paths*."""
        wanted = set(file_paths)
        for raw in self._iter_files():
            if raw.path in wanted:
                yield raw

    def metadata(self) -> SourceMetadata:
        files = list(self._iter_files())
        return SourceMetadata(label=self.label(), languages=detect_languages(files))

    def head_sha(self) -> str | None:
        """Return the current HEAD commit SHA for the local git repo, or None."""
        import shutil  # noqa: PLC0415

        git_exe = shutil.which("git") or "git"
        try:
            result = subprocess.run(
                [git_exe, "-C", str(self.root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            return result.stdout.strip() or None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def diff_files(self, old_sha: str, new_sha: str) -> list[str]:
        """Return file paths changed between *old_sha* and *new_sha* (relative, forward-slash).

        Includes added, modified, and deleted files.  Only files that would
        normally be loaded (not ignored) are returned.
        """
        import shutil as _shutil  # noqa: PLC0415

        git_exe = _shutil.which("git") or "git"
        try:
            result = subprocess.run(
                [git_exe, "-C", str(self.root), "diff", "--name-only", old_sha, new_sha],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
            return [p for p in paths if not _should_ignore(p)]
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return []
