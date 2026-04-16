"""Documentation generation subpackage."""

from __future__ import annotations

from .generator import DocScope, GenerationCancelled, generate_docs

__all__ = [
    "DocScope",
    "GenerationCancelled",
    "generate_docs",
]
