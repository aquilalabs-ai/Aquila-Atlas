"""Zip archive source loader."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import SourceMetadata
from aquila_atlas.ingestion.sources._common import RawFile, _should_ignore

if TYPE_CHECKING:
    from collections.abc import Iterator


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