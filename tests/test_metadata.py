"""Tests for the ingestion metadata dataclasses."""

from __future__ import annotations

import pytest

from aquila_atlas.ingestion.metadata import CodeChunk, CodeEntity, SourceMetadata

# ---------------------------------------------------------------------------
# SourceMetadata
# ---------------------------------------------------------------------------


def test_source_metadata_defaults() -> None:
    meta = SourceMetadata(label="my-repo")
    assert meta.label == "my-repo"
    assert meta.commit_sha is None
    assert meta.branch is None
    assert meta.languages == {}


def test_source_metadata_full() -> None:
    meta = SourceMetadata(
        label="https://github.com/org/repo",
        commit_sha="abc123",
        branch="main",
        languages={"Python": 4096, "JavaScript": 2048},
    )
    assert meta.commit_sha == "abc123"
    assert meta.branch == "main"
    assert meta.languages["Python"] == 4096


def test_source_metadata_is_frozen() -> None:
    meta = SourceMetadata(label="test")
    with pytest.raises((AttributeError, TypeError)):
        meta.label = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CodeEntity
# ---------------------------------------------------------------------------


def _make_entity(**kwargs: object) -> CodeEntity:
    defaults: dict[str, object] = {
        "type": "function",
        "name": "my_func",
        "qualified_name": "my_func",
        "file_path": "src/mod.py",
        "start_line": 1,
        "end_line": 5,
        "source": "def my_func(): pass\n",
    }
    defaults.update(kwargs)
    return CodeEntity(**defaults)  # type: ignore[arg-type]


def test_code_entity_defaults() -> None:
    e = _make_entity()
    assert e.docstring is None
    assert e.parent is None
    assert e.imports == ()
    assert e.decorators == ()
    assert e.visibility == "public"
    assert e.is_async is False


def test_code_entity_method_visibility() -> None:
    e = _make_entity(
        type="method",
        name="_helper",
        qualified_name="MyClass._helper",
        parent="MyClass",
        visibility="private",
    )
    assert e.visibility == "private"
    assert e.parent == "MyClass"
    assert e.qualified_name == "MyClass._helper"


def test_code_entity_async() -> None:
    e = _make_entity(type="function", name="fetch", is_async=True)
    assert e.is_async is True


def test_code_entity_with_imports() -> None:
    e = _make_entity(type="file", imports=("os", "sys", "pathlib"))
    assert "os" in e.imports
    assert len(e.imports) == 3


def test_code_entity_with_decorators() -> None:
    e = _make_entity(decorators=("property", "staticmethod"))
    assert "property" in e.decorators


def test_code_entity_is_frozen() -> None:
    e = _make_entity()
    with pytest.raises((AttributeError, TypeError)):
        e.name = "other"  # type: ignore[misc]


def test_code_entity_interface_type() -> None:
    e = _make_entity(type="interface", name="IService", qualified_name="IService")
    assert e.type == "interface"


# ---------------------------------------------------------------------------
# CodeChunk
# ---------------------------------------------------------------------------


def test_code_chunk_basic() -> None:
    entity = _make_entity()
    chunk = CodeChunk(
        entity=entity,
        content="def my_func(): pass\n",
        token_count=10,
        chunk_index=0,
        chunk_total=1,
    )
    assert chunk.chunk_index == 0
    assert chunk.chunk_total == 1
    assert chunk.token_count == 10
    assert chunk.start_line == 0  # default
    assert chunk.end_line == 0  # default


def test_code_chunk_with_line_range() -> None:
    entity = _make_entity()
    chunk = CodeChunk(
        entity=entity,
        content="x = 1\n",
        token_count=5,
        chunk_index=1,
        chunk_total=3,
        start_line=10,
        end_line=20,
    )
    assert chunk.start_line == 10
    assert chunk.end_line == 20
    assert chunk.chunk_total == 3


def test_code_chunk_entity_reference() -> None:
    entity = _make_entity(name="target_func")
    chunk = CodeChunk(
        entity=entity,
        content="def target_func(): ...\n",
        token_count=8,
        chunk_index=0,
        chunk_total=1,
    )
    assert chunk.entity.name == "target_func"
    assert chunk.entity.file_path == "src/mod.py"
