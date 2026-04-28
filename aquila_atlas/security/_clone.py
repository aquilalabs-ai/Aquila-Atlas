"""Source resolver: yields a local filesystem path for any source type.

Local paths pass through unchanged.
Remote git URLs are shallow-cloned and cleaned up automatically.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from aquila_atlas.ingestion.sources._common import temporary_clone

_REMOTE_SCHEMES = ("http://", "https://", "git@", "ssh://", "git://")


def is_remote(source: str) -> bool:
    return any(source.startswith(s) for s in _REMOTE_SCHEMES)


@contextlib.contextmanager
def resolve_source(source: str, token: str = "", branch: str = "") -> Iterator[str]:
    """Context manager that yields a local directory path.

    Usage::

        with resolve_source("https://github.com/owner/repo") as local_path:
            run_semgrep(local_path)
    """
    with temporary_clone(source, token=token, branch=branch) as local_path:  # type: ignore[attr-defined]
        yield local_path
