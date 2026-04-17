"""Tests for the ingestion layer."""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

from aquila_atlas.ingestion.chunker import chunk_entity
from aquila_atlas.ingestion.metadata import CodeEntity
from aquila_atlas.ingestion.parsers import parse, parse_python
from aquila_atlas.ingestion.sources import (
    LocalFolderLoader,
    RawFile,
    ZipLoader,
    detect_languages,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# ZipLoader
# ---------------------------------------------------------------------------


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_zip_loader() -> None:
    zip_bytes = _make_zip(
        {
            "myproject/src/main.py": b"print('hello')",
            "myproject/README.md": b"# Readme",
        }
    )
    loader = ZipLoader(zip_bytes)
    results = list(loader.load())
    paths = {r.path for r in results}
    assert paths == {"src/main.py", "README.md"}
    contents = {r.path: r.content for r in results}
    assert contents["src/main.py"] == b"print('hello')"
    assert contents["README.md"] == b"# Readme"


# ---------------------------------------------------------------------------
# LocalFolderLoader
# ---------------------------------------------------------------------------


def test_local_folder_loader(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(b"x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "helper.py").write_bytes(b"y = 2\n")

    loader = LocalFolderLoader(tmp_path)
    results = list(loader.load())
    paths = {r.path for r in results}
    assert "app.py" in paths
    assert "sub/helper.py" in paths


def test_local_folder_loader_ignores_pycache(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(b"x = 1\n")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "app.cpython-313.pyc").write_bytes(b"\x00\x01\x02")

    loader = LocalFolderLoader(tmp_path)
    results = list(loader.load())
    paths = {r.path for r in results}
    assert "app.py" in paths
    assert not any("__pycache__" in p for p in paths)


# ---------------------------------------------------------------------------
# detect_languages
# ---------------------------------------------------------------------------


def test_detect_languages() -> None:
    files = [
        RawFile(path="main.py", content=b"x" * 100),
        RawFile(path="app.js", content=b"y" * 200),
        RawFile(path="style.py", content=b"z" * 50),
        RawFile(path="unknown.xyz", content=b"w" * 10),
    ]
    langs = detect_languages(files)
    assert langs["Python"] == 150
    assert langs["JavaScript"] == 200
    assert "unknown" not in langs


# ---------------------------------------------------------------------------
# parse_python — function
# ---------------------------------------------------------------------------


def test_parse_python_function() -> None:
    source = '''\
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}"
'''
    entities = parse_python(source, "greet.py")
    types = {e.type for e in entities}
    assert "file" in types
    assert "function" in types

    func = next(e for e in entities if e.type == "function")
    assert func.name == "greet"
    assert func.qualified_name == "greet"
    assert func.docstring == "Return a greeting."
    assert func.start_line == 1
    assert func.end_line == 3


# ---------------------------------------------------------------------------
# parse_python — class with methods
# ---------------------------------------------------------------------------


def test_parse_python_class() -> None:
    source = '''\
class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
'''
    entities = parse_python(source, "calc.py")
    entity_types = [e.type for e in entities]
    assert "file" in entity_types
    assert "class" in entity_types
    assert entity_types.count("method") == 2

    cls = next(e for e in entities if e.type == "class")
    assert cls.name == "Calculator"
    assert cls.docstring == "A simple calculator."

    methods = [e for e in entities if e.type == "method"]
    method_names = {m.name for m in methods}
    assert method_names == {"add", "subtract"}

    add_method = next(m for m in methods if m.name == "add")
    assert add_method.qualified_name == "Calculator.add"
    assert add_method.parent == "Calculator"
    assert add_method.docstring == "Add two numbers."


# ---------------------------------------------------------------------------
# chunk_entity — small (fits in single chunk)
# ---------------------------------------------------------------------------


def test_chunk_entity_small() -> None:
    entity = CodeEntity(
        type="function",
        name="tiny",
        qualified_name="tiny",
        file_path="tiny.py",
        start_line=1,
        end_line=2,
        source="def tiny():\n    pass\n",
    )
    chunks = chunk_entity(entity, max_tokens=512)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_total == 1
    assert chunks[0].content == entity.source


# ---------------------------------------------------------------------------
# chunk_entity — large (requires splitting)
# ---------------------------------------------------------------------------


def test_chunk_entity_large() -> None:
    # Build a source that clearly exceeds 512 tokens
    lines = [f"x_{i} = {i}  # padding comment to increase token count\n" for i in range(200)]
    source = "".join(lines)
    entity = CodeEntity(
        type="file",
        name="big",
        qualified_name="big.py",
        file_path="big.py",
        start_line=1,
        end_line=200,
        source=source,
    )
    chunks = chunk_entity(entity, max_tokens=512, overlap_tokens=50)
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i
        assert chunk.chunk_total == len(chunks)
        assert chunk.token_count <= 512 + 50  # slight tolerance for overlap


# ---------------------------------------------------------------------------
# parse dispatch — non-Python file
# ---------------------------------------------------------------------------


def test_parse_non_python() -> None:
    raw = RawFile(path="style.css", content=b"body { margin: 0; }\n")
    entities = parse(raw)
    assert len(entities) == 1
    assert entities[0].type == "file"
    assert entities[0].name == "style.css"


# ---------------------------------------------------------------------------
# ZipLoader metadata
# ---------------------------------------------------------------------------


def test_zip_loader_metadata() -> None:
    zip_bytes = _make_zip({"proj/main.py": b"pass\n"})
    loader = ZipLoader(zip_bytes)
    meta = loader.metadata()
    assert meta.label == "<zip bytes>"
    assert meta.commit_sha is None


# ---------------------------------------------------------------------------
# LocalFolderLoader metadata
# ---------------------------------------------------------------------------


def test_local_folder_loader_metadata(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(b"x" * 80)
    loader = LocalFolderLoader(tmp_path)
    meta = loader.metadata()
    assert meta.label == str(tmp_path)
    assert meta.languages.get("Python", 0) == 80


# ---------------------------------------------------------------------------
# COBOL parser — via parse() dispatch
# ---------------------------------------------------------------------------


def test_parse_cobol_basic() -> None:
    source = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'Hello World'.
           STOP RUN.
"""
    raw = RawFile(path="hello.cbl", content=source)
    entities = parse(raw)
    assert len(entities) >= 1
    types = {e.type for e in entities}
    # At minimum a file-level entity must be produced
    assert "file" in types or "class" in types or "function" in types


def test_parse_cobol_extracts_paragraph() -> None:
    source = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       PROCEDURE DIVISION.
       CALCULATE-PAY.
           MULTIPLY HOURS BY RATE GIVING GROSS-PAY.
           STOP RUN.
"""
    raw = RawFile(path="payroll.cbl", content=source)
    entities = parse(raw)
    names = {e.name for e in entities}
    # CALCULATE-PAY should be extracted as a paragraph/function
    assert any("CALCULATE-PAY" in n or "PAYROLL" in n for n in names)


def test_parse_cobol_copybook() -> None:
    source = b"""\
       01 CUSTOMER-RECORD.
          05 CUST-ID     PIC 9(6).
          05 CUST-NAME   PIC X(30).
"""
    raw = RawFile(path="customer.cpy", content=source)
    entities = parse(raw)
    assert len(entities) >= 1


# ---------------------------------------------------------------------------
# JavaScript parser — via parse() dispatch
# ---------------------------------------------------------------------------


def test_parse_javascript_function() -> None:
    source = b"""\
function greet(name) {
    return `Hello, ${name}`;
}
"""
    raw = RawFile(path="greet.js", content=source)
    entities = parse(raw)
    types = {e.type for e in entities}
    assert "function" in types or "file" in types
    func_names = {e.name for e in entities if e.type == "function"}
    assert "greet" in func_names


def test_parse_typescript_interface() -> None:
    source = b"""\
interface User {
    id: number;
    name: string;
}

function getUser(id: number): User {
    return { id, name: 'Alice' };
}
"""
    raw = RawFile(path="user.ts", content=source)
    entities = parse(raw)
    names = {e.name for e in entities}
    assert "getUser" in names or "User" in names
