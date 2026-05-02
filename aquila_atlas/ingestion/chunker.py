"""Token-aware chunker — split CodeEntity objects into embedding-ready chunks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import tiktoken

from aquila_atlas.ingestion.metadata import CodeChunk, CodeEntity

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from aquila_atlas.ingestion.sources import RawFile

_DEFAULT_ENCODING = "cl100k_base"


def _get_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_DEFAULT_ENCODING)


def chunk_entity(
    entity: CodeEntity,
    max_tokens: int = 512,
    overlap_tokens: int = 50,
) -> list[CodeChunk]:
    """Split a single CodeEntity into token-bounded CodeChunk objects."""
    enc = _get_encoding()
    full_tokens = enc.encode(entity.source)

    if len(full_tokens) <= max_tokens:
        return [
            CodeChunk(
                entity=entity,
                content=entity.source,
                token_count=len(full_tokens),
                chunk_index=0,
                chunk_total=1,
                start_line=entity.start_line,
                end_line=entity.end_line,
            )
        ]

    # Split by lines, accumulate up to max_tokens, then overlap.
    # Track the 0-based line offset within the entity so each sub-chunk gets
    # its own absolute start_line / end_line in the original file.
    lines = entity.source.splitlines(keepends=True)
    # (chunk_lines, start_offset_within_entity)
    chunks_data: list[tuple[list[str], int]] = []
    current_lines: list[str] = []
    current_token_count = 0
    current_start_offset = 0  # 0-based index into `lines`

    for line in lines:
        line_tokens = len(enc.encode(line))
        if current_token_count + line_tokens > max_tokens and current_lines:
            chunks_data.append((list(current_lines), current_start_offset))
            # Build overlap: take lines from the end until we have overlap_tokens
            overlap_lines: list[str] = []
            overlap_count = 0
            for prev_line in reversed(current_lines):
                prev_tokens = len(enc.encode(prev_line))
                if overlap_count + prev_tokens > overlap_tokens:
                    break
                overlap_lines.insert(0, prev_line)
                overlap_count += prev_tokens
            # New chunk starts after the non-overlapping portion of the previous chunk
            current_start_offset += len(current_lines) - len(overlap_lines)
            current_lines = overlap_lines + [line]
            current_token_count = overlap_count + line_tokens
        else:
            current_lines.append(line)
            current_token_count += line_tokens

    if current_lines:
        chunks_data.append((list(current_lines), current_start_offset))

    total = len(chunks_data)
    return [
        CodeChunk(
            entity=entity,
            content="".join(chunk_lines),
            token_count=len(enc.encode("".join(chunk_lines))),
            chunk_index=i,
            chunk_total=total,
            start_line=entity.start_line + start_offset,
            end_line=entity.start_line + start_offset + len(chunk_lines) - 1,
        )
        for i, (chunk_lines, start_offset) in enumerate(chunks_data)
    ]


def chunk_file_summary(entities: list[CodeEntity]) -> CodeChunk | None:
    """Build a single summary chunk for a file from its parsed entities.

    Returns None if no file-level entity is found (e.g. binary / undecodable file).
    The summary is a structured text description of the file's contents — small
    enough to always fit in one chunk and useful for orientation during retrieval.
    """
    file_entity = next((e for e in entities if e.type == "file"), None)
    if file_entity is None:
        return None

    classes = [e for e in entities if e.type == "class"]
    functions = [e for e in entities if e.type == "function"]
    methods = [e for e in entities if e.type == "method"]

    lines: list[str] = [f"File: {file_entity.file_path}"]

    if file_entity.imports:
        lines.append(f"Imports: {', '.join(file_entity.imports)}")

    if file_entity.docstring:
        lines.append(f"Summary: {file_entity.docstring}")

    if classes:
        lines.append("\nClasses:")
        for cls in classes:
            prefix = f"  {cls.name}"
            if cls.docstring:
                lines.append(f"{prefix} — {cls.docstring.splitlines()[0]}")
            else:
                lines.append(prefix)
            cls_methods = [m for m in methods if m.parent == cls.name]
            for m in cls_methods:
                vis = "" if m.visibility == "public" else f"[{m.visibility}] "
                async_tag = "async " if m.is_async else ""
                dec = f"  @{', @'.join(m.decorators)} " if m.decorators else ""
                doc = f" — {m.docstring.splitlines()[0]}" if m.docstring else ""
                lines.append(f"    {dec}{vis}{async_tag}{m.name}(){doc}")

    if functions:
        lines.append("\nFunctions:")
        for fn in functions:
            vis = "" if fn.visibility == "public" else f"[{fn.visibility}] "
            async_tag = "async " if fn.is_async else ""
            dec = f"@{', @'.join(fn.decorators)} " if fn.decorators else ""
            doc = f" — {fn.docstring.splitlines()[0]}" if fn.docstring else ""
            lines.append(f"  {dec}{vis}{async_tag}{fn.name}(){doc}")

    content = "\n".join(lines)
    enc = _get_encoding()
    token_count = len(enc.encode(content))

    return CodeChunk(
        entity=file_entity,
        content=content,
        token_count=token_count,
        chunk_index=0,
        chunk_total=1,
        start_line=file_entity.start_line,
        end_line=file_entity.end_line,
    )


def chunk_files(
    files: Iterable[RawFile],
    max_tokens: int = 512,
) -> Iterator[CodeChunk]:
    """Parse each file, chunk each entity, and yield all resulting CodeChunks.

    For each file, a file-level summary chunk is emitted first, followed by
    one or more chunks per parsed entity (function, class, method).
    """
    from aquila_atlas.ingestion.parsers import parse

    for file in files:
        entities = parse(file)
        summary = chunk_file_summary(entities)
        if summary is not None:
            yield summary
        for entity in entities:
            yield from chunk_entity(entity, max_tokens=max_tokens)
