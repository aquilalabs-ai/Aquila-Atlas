"""Shared data models for the ingestion layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SourceMetadata:
    """High-level metadata about an ingested source."""

    label: str
    commit_sha: str | None = None
    branch: str | None = None
    languages: dict[str, int] = field(default_factory=dict)  # language -> byte count


EntityType = Literal["file", "class", "function", "method", "interface"]
Visibility = Literal["public", "private", "mangled"]


@dataclass(frozen=True)
class CodeEntity:
    """A parsed code entity extracted from a source file."""

    type: EntityType
    name: str
    qualified_name: str  # e.g. "MyClass.my_method"
    file_path: str
    start_line: int
    end_line: int
    source: str
    docstring: str | None = None
    parent: str | None = None  # qualified_name of the parent entity
    # Import statements — populated on file-level entities only
    imports: tuple[str, ...] = field(default_factory=tuple)
    # Decorator names/expressions — populated on class/function/method entities
    decorators: tuple[str, ...] = field(default_factory=tuple)
    # Naming-convention visibility (public / _private / __mangled)
    visibility: Visibility = "public"
    # True for async def functions and methods
    is_async: bool = False


@dataclass(frozen=True)
class CodeChunk:
    """A token-bounded slice of a CodeEntity, ready for embedding."""

    entity: CodeEntity
    content: str
    token_count: int
    chunk_index: int  # 0-based
    chunk_total: int
