"""Ingestion layer — source loaders, AST parser, and chunker."""

from aquila_atlas.ingestion.chunker import chunk_entity, chunk_file_summary, chunk_files
from aquila_atlas.ingestion.metadata import CodeChunk, CodeEntity, SourceMetadata
from aquila_atlas.ingestion.parser import parse
from aquila_atlas.ingestion.sources import (
    GitHubLoader,
    LocalFolderLoader,
    RawFile,
    SourceLoader,
    ZipLoader,
)

__all__ = [
    "GitHubLoader",
    "LocalFolderLoader",
    "RawFile",
    "SourceLoader",
    "ZipLoader",
    "SourceMetadata",
    "CodeEntity",
    "CodeChunk",
    "parse",
    "chunk_entity",
    "chunk_file_summary",
    "chunk_files",
]
