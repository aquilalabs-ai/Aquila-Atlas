"""COBOL language plugin for Aquila-Atlas.

Parses COBOL source files (.cbl, .cob, .cobol) and copybooks (.cpy)
into :class:`~aquila_atlas.ingestion.metadata.CodeEntity` objects that
the knowledge graph and vector store can index.

Handles two sequence-number formats:
- With sequence numbers: cols 1-6 are digits (e.g. 000100)
- Without sequence numbers: cols 1-6 are spaces

Extracted entities
------------------
- ``file``      — one per file; name = PROGRAM-ID; docstring = header comments;
                  imports = COPY / EXEC SQL INCLUDE references
- ``class``     — one per DIVISION (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
- ``function``  — one per PARAGRAPH inside the PROCEDURE DIVISION;
                  docstring = adjacent comment block; source = paragraph lines
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from aquila_atlas.ingestion.metadata import CodeEntity


# ---------------------------------------------------------------------------
# Internal COBOL AST types
# ---------------------------------------------------------------------------


@dataclass
class _Paragraph:
    name: str
    start_line: int  # 1-based
    end_line: int = 0
    comments: list[str] = field(default_factory=list)
    perform_targets: list[str] = field(default_factory=list)
    external_calls: list[str] = field(default_factory=list)


@dataclass
class _Division:
    name: str
    start_line: int  # 1-based
    end_line: int = 0  # exclusive, 1-based


@dataclass
class _ParsedCobol:
    file_path: str
    file_name: str
    file_type: str
    has_sequence_numbers: bool
    header_comments: list[str] = field(default_factory=list)
    program_id: str = ""
    program_description: str = ""
    program_layer: str = ""
    divisions: list[_Division] = field(default_factory=list)
    paragraphs: list[_Paragraph] = field(default_factory=list)
    copy_references: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # normalised (seq stripped)
    raw_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Low-level line helpers
# ---------------------------------------------------------------------------


def _detect_sequence_numbers(raw_lines: list[str]) -> bool:
    """Return True if the file uses 6-digit sequence numbers in cols 1-6."""
    for line in raw_lines[:30]:
        if len(line) >= 7 and line[:6].strip():
            return bool(re.match(r"^\d{6}", line))
    return False


def _strip_sequence(line: str, has_seq: bool) -> str:
    if has_seq and len(line) >= 6 and re.match(r"^\d{6}", line):
        return line[6:]
    return line


def _is_comment(cobol_line: str) -> bool:
    """True when COBOL indicator column (position 7 after stripping seq) is '*'."""
    stripped = cobol_line.lstrip()
    if stripped.startswith("*"):
        return True
    # Column 7 in a 72-col fixed line
    if len(cobol_line) >= 7 and cobol_line[6] == "*":
        return True
    return False


# ---------------------------------------------------------------------------
# Parsing passes
# ---------------------------------------------------------------------------


def _extract_header_comments(parsed: _ParsedCobol) -> None:
    comments: list[str] = []
    for line in parsed.lines:
        stripped = line.strip()
        if stripped.startswith("*"):
            comments.append(stripped.lstrip("*").strip())
        elif not stripped:
            if comments:
                break
        else:
            break
    parsed.header_comments = comments

    for c in comments:
        m = re.match(r"(?:Function|FUNCTION)\s*:?\s*(.+)", c)
        if m:
            parsed.program_description = m.group(1).strip().rstrip("*").strip()
        m = re.match(r"(?:Layer|LAYER|Type|TYPE)\s*:?\s*(.+)", c)
        if m and not parsed.program_layer:
            parsed.program_layer = m.group(1).strip().rstrip("*").strip()


def _extract_program_id(parsed: _ParsedCobol) -> None:
    for i, line in enumerate(parsed.lines):
        if "PROGRAM-ID" in line.upper():
            m = re.search(r"PROGRAM-ID\.?\s+(\w+)", line, re.IGNORECASE)
            if m:
                parsed.program_id = m.group(1).upper()
            elif i + 1 < len(parsed.lines):
                next_line = parsed.lines[i + 1].strip().rstrip(".")
                parsed.program_id = next_line.strip().upper()
            break


def _extract_divisions(parsed: _ParsedCobol) -> None:
    divisions: list[_Division] = []
    div_pattern = re.compile(
        r"^\s+(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION",
        re.IGNORECASE,
    )
    for i, line in enumerate(parsed.lines):
        m = div_pattern.match(line)
        if m:
            div_name = m.group(1).upper()
            if divisions:
                divisions[-1].end_line = i + 1  # 1-based exclusive
            divisions.append(_Division(name=div_name, start_line=i + 1))

    if divisions:
        divisions[-1].end_line = len(parsed.lines) + 1
    parsed.divisions = divisions


_PERFORM_RE = re.compile(r"PERFORM\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_CALL_RE = re.compile(r"\bCALL\s+['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?", re.IGNORECASE)
_CICS_RE = re.compile(
    r"\bEXEC\s+CICS\s+(?:LINK|XCTL)\s+PROGRAM\s*\(\s*['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?",
    re.IGNORECASE,
)
# Paragraph header: name starting in area A (cols 8-11 → position 7+ after stripping seq)
_PARA_RE = re.compile(r"^       ([A-Z0-9][A-Z0-9-]*)\.\s*$", re.IGNORECASE)


def _extract_paragraphs(parsed: _ParsedCobol) -> None:
    proc_div = next((d for d in parsed.divisions if d.name == "PROCEDURE"), None)
    if not proc_div:
        return

    # Convert to 0-based indices for list slicing
    proc_start = proc_div.start_line  # 1-based → index proc_start-1
    proc_end = proc_div.end_line - 1  # exclusive 1-based → exclusive 0-based

    paragraphs: list[_Paragraph] = []
    lines = parsed.lines

    for i in range(proc_start, proc_end):  # 0-based
        line = lines[i] if i < len(lines) else ""
        m = _PARA_RE.match(line)
        if not m:
            continue
        para_name = m.group(1).upper()

        # Gather preceding comment block
        comments: list[str] = []
        j = i - 1
        while j >= proc_start - 1:
            prev = lines[j].strip()
            if prev.startswith("*"):
                comments.insert(0, prev.lstrip("*").strip())
                j -= 1
            elif not prev:
                j -= 1
            else:
                break

        if paragraphs:
            paragraphs[-1].end_line = i + 1  # 1-based exclusive

        paragraphs.append(_Paragraph(name=para_name, start_line=i + 1, comments=comments))

    if paragraphs:
        paragraphs[-1].end_line = proc_div.end_line

    # PERFORM / CALL analysis per paragraph
    for para in paragraphs:
        # 0-based slice
        start_idx = para.start_line - 1
        end_idx = min(para.end_line - 1, len(lines))
        targets: set[str] = set()
        external: set[str] = set()
        for line in lines[start_idx:end_idx]:
            for mm in _PERFORM_RE.finditer(line):
                target = mm.group(1).upper()
                if target not in ("UNTIL", "VARYING", "WITH", "THRU", "THROUGH", "TIMES"):
                    targets.add(target)
            for mm in _CALL_RE.finditer(line):
                external.add(f"CALL {mm.group(1).upper()}")
            for mm in _CICS_RE.finditer(line):
                external.add(f"CICS {mm.group(1).upper()}")
        para.perform_targets = sorted(targets)
        para.external_calls = sorted(external)

    parsed.paragraphs = paragraphs


def _extract_copy_references(parsed: _ParsedCobol) -> None:
    refs: list[str] = []
    copy_pattern = re.compile(r"\bCOPY\s+([A-Z0-9]+)", re.IGNORECASE)
    sql_include = re.compile(
        r"\bEXEC\s+SQL\s+INCLUDE\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE
    )
    for line in parsed.lines:
        if line.strip().startswith("*"):
            continue
        for m in copy_pattern.finditer(line):
            ref = m.group(1).upper()
            if ref not in refs:
                refs.append(ref)
        for m in sql_include.finditer(line):
            ref = f"SQL:{m.group(1).upper()}"
            if ref not in refs:
                refs.append(ref)
    parsed.copy_references = refs


# ---------------------------------------------------------------------------
# Top-level parse function
# ---------------------------------------------------------------------------


def _parse_cobol(source_bytes: bytes, file_path: str) -> _ParsedCobol:
    text = source_bytes.decode("utf-8", errors="replace")
    raw_lines = text.splitlines()
    has_seq = _detect_sequence_numbers(raw_lines)
    lines = [_strip_sequence(line, has_seq) for line in raw_lines]

    path = Path(file_path)
    suffix = path.suffix.lower().lstrip(".")
    file_type = "cbl" if suffix in ("cbl", "cob", "cobol") else "cpy"

    parsed = _ParsedCobol(
        file_path=file_path,
        file_name=path.name,
        file_type=file_type,
        has_sequence_numbers=has_seq,
        lines=lines,
        raw_lines=raw_lines,
    )
    _extract_header_comments(parsed)
    _extract_program_id(parsed)
    _extract_divisions(parsed)
    _extract_paragraphs(parsed)
    _extract_copy_references(parsed)
    return parsed


# ---------------------------------------------------------------------------
# Map _ParsedCobol → list[CodeEntity]
# ---------------------------------------------------------------------------


def parse_cobol(source_bytes: bytes, file_path: str) -> list[CodeEntity]:
    """Parse a COBOL source file and return a flat list of :class:`CodeEntity`."""
    parsed = _parse_cobol(source_bytes, file_path)
    lines = parsed.lines
    total_lines = len(lines) if lines else 1
    text = "\n".join(lines)
    path = Path(file_path)

    header_doc = "\n".join(parsed.header_comments) if parsed.header_comments else None
    if parsed.program_description:
        header_doc = (header_doc + "\n\n" + parsed.program_description) if header_doc else parsed.program_description

    # Program-ID as name; fall back to stem when PROGRAM-ID is absent (copybooks)
    prog_name = parsed.program_id or path.stem.upper()

    entities: list[CodeEntity] = [
        CodeEntity(
            type="file",
            name=prog_name,
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=total_lines,
            source=text,
            docstring=header_doc,
            imports=tuple(parsed.copy_references),
        )
    ]

    # One "class" entity per DIVISION
    for div in parsed.divisions:
        div_lines = lines[div.start_line - 1 : div.end_line - 1]
        div_source = "\n".join(div_lines)
        div_end = min(div.end_line - 1, total_lines)
        entities.append(
            CodeEntity(
                type="class",
                name=f"{div.name} DIVISION",
                qualified_name=f"{file_path}::{div.name}_DIVISION",
                file_path=file_path,
                start_line=div.start_line,
                end_line=div_end,
                source=div_source,
                parent=file_path,
            )
        )

    # One "function" entity per PARAGRAPH
    for para in parsed.paragraphs:
        para_lines = lines[para.start_line - 1 : para.end_line - 1]
        para_source = "\n".join(para_lines)
        para_end = min(para.end_line - 1, total_lines)
        doc = "\n".join(para.comments) if para.comments else None
        if para.perform_targets or para.external_calls:
            calls_note = []
            if para.perform_targets:
                calls_note.append("PERFORMS: " + ", ".join(para.perform_targets))
            if para.external_calls:
                calls_note.append("CALLS: " + ", ".join(para.external_calls))
            extra = " | ".join(calls_note)
            doc = (doc + "\n" + extra) if doc else extra

        entities.append(
            CodeEntity(
                type="function",
                name=para.name,
                qualified_name=f"{file_path}::{para.name}",
                file_path=file_path,
                start_line=para.start_line,
                end_line=para_end,
                source=para_source,
                docstring=doc,
                parent=f"{file_path}::PROCEDURE_DIVISION",
            )
        )

    return entities


# ---------------------------------------------------------------------------
# Call extraction  (PERFORM → paragraph edges)
# ---------------------------------------------------------------------------


def _extract_cobol_calls(entities: list[CodeEntity]) -> list[tuple[str, str, str]]:
    """Return ``(caller_qn, caller_fp, callee_name)`` triples.

    Each PERFORM target becomes a call edge. The callee_name is the paragraph
    name; the graph store will match it against qualified_names of the form
    ``<file_path>::<PARA_NAME>``.
    """
    results: list[tuple[str, str, str]] = []
    for entity in entities:
        if entity.type != "function":
            continue
        # Extract PERFORM targets from the docstring annotation we embedded
        if entity.docstring and "PERFORMS:" in entity.docstring:
            for line in entity.docstring.splitlines():
                if line.startswith("PERFORMS:"):
                    targets_str = line[len("PERFORMS:"):].strip()
                    for target in targets_str.split(","):
                        target = target.strip()
                        if target:
                            results.append((entity.qualified_name, entity.file_path, target))
    return results


# ---------------------------------------------------------------------------
# Import resolution  (COPY <name> → .cpy file in the repo)
# ---------------------------------------------------------------------------


def _resolve_cobol_import(
    import_str: str,
    _importer_path: str,
    known_files: dict[str, str],
) -> str | None:
    """Map a COPY reference to a known in-repo .cpy file ID.

    ``import_str`` is the bare copybook name as extracted by
    ``_extract_copy_references`` — e.g. ``"CUSTFILE"`` or ``"SQL:CUSTFILE"``.
    SQL includes (``"SQL:NAME"``) are resolved the same way as plain COPY
    references; the ``"SQL:"`` prefix is stripped before matching.

    Matching is case-insensitive on the file stem; directory location is
    ignored so copybooks kept in a dedicated ``copy/`` or ``copylib/`` folder
    are found regardless of where the importer lives.
    """
    # Strip SQL: prefix used for EXEC SQL INCLUDE references
    name = import_str.removeprefix("SQL:").upper()

    for file_path, file_id in known_files.items():
        normalized = file_path.replace("\\", "/")
        stem = normalized.rsplit("/", 1)[-1]  # filename only
        if "." in stem:
            stem, ext = stem.rsplit(".", 1)
            if ext.lower() == "cpy" and stem.upper() == name:
                return file_id
    return None


# ---------------------------------------------------------------------------
# Language plugin registration
# ---------------------------------------------------------------------------

from aquila_atlas.ingestion.language import LanguagePlugin, register  # noqa: E402

_COBOL_PLUGIN = LanguagePlugin(
    name="COBOL",
    extensions=frozenset({".cbl", ".cob", ".cobol", ".cpy"}),
    parse_file=parse_cobol,
    extract_calls=_extract_cobol_calls,
    resolve_import=_resolve_cobol_import,
)
register(_COBOL_PLUGIN)
