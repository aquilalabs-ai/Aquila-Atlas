"""Backward-compatibility shim — re-exports from the new docs/ subpackage.

All code has moved to :mod:`aquila_atlas.reasoning.docs`.
This module is kept so existing imports continue to work without changes.
"""

from __future__ import annotations

from aquila_atlas.reasoning.docs import DocScope, GenerationCancelled, generate_docs

__all__ = [
    "DocScope",
    "GenerationCancelled",
    "generate_docs",
]
