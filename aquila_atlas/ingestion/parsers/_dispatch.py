"""Public parse() dispatcher — routes files to the correct language plugin."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.metadata import CodeEntity

if TYPE_CHECKING:
    from aquila_atlas.ingestion.sources._common import RawFile


def parse(file: RawFile) -> list[CodeEntity]:
    """Dispatch to the appropriate language plugin, falling back to a single
    file-level entity for unsupported extensions."""
    from aquila_atlas.ingestion.language import get_plugin  # lazy — avoids circular import

    suffix = Path(file.path).suffix.lower()
    plugin = get_plugin(suffix)
    if plugin is not None:
        return plugin.parse_file(file.content, file.path)

    # Unsupported extension: single file-level entity preserving raw text.
    try:
        text = file.content.decode("utf-8")
    except UnicodeDecodeError:
        return []
    line_count = text.count("\n") + (1 if text else 0)
    return [
        CodeEntity(
            type="file",
            name=Path(file.path).name,
            qualified_name=file.path,
            file_path=file.path,
            start_line=1,
            end_line=line_count,
            source=text,
        )
    ]
