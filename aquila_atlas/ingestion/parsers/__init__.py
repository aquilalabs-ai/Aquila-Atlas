"""Language parsers — dispatch and per-language implementations."""

from aquila_atlas.ingestion.parsers._dispatch import parse
from aquila_atlas.ingestion.parsers.python import parse_python

__all__ = ["parse", "parse_python"]
