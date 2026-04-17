"""COBOL language plugin for Aquila-Atlas.

Parses COBOL source files (.cbl, .cob, .cobol) and copybooks (.cpy)
into :class:`~aquila_atlas.ingestion.metadata.CodeEntity` objects that
the knowledge graph and vector store can index.

Handles multiple COBOL source formats
--------------------------------------
- Fixed format with 6-digit sequence numbers (cols 1-6)
- Fixed format without sequence numbers (blank cols 1-6)
- Free format (COBOL 2002+, ``>>SOURCE FORMAT FREE`` directive)
- Continuation lines (indicator column = ``-``)
- UTF-8, Latin-1 / cp1252 encoded files (common mainframe exports)

Extracted entities
------------------
- ``file``     — one per PROGRAM-ID; docstring = header comments + author metadata;
                 imports = COPY / EXEC SQL INCLUDE references
- ``class``    — one per DIVISION; one per SECTION inside PROCEDURE DIVISION;
                 one per 01-level record / FD entry in DATA DIVISION
- ``function`` — one per PARAGRAPH inside PROCEDURE DIVISION
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
    section: str = ""  # enclosing SECTION name (empty if none)


@dataclass
class _Section:
    name: str
    start_line: int  # 1-based
    end_line: int = 0


@dataclass
class _Division:
    name: str
    start_line: int  # 1-based
    end_line: int = 0  # exclusive, 1-based


@dataclass
class _DataRecord:
    name: str
    section_name: str  # WORKING-STORAGE, FILE, LINKAGE, LOCAL-STORAGE, …
    start_line: int  # 1-based
    end_line: int = 0
    pic: str = ""  # PIC clause value if elementary item


@dataclass
class _ParsedCobol:
    file_path: str
    file_name: str
    file_type: str
    has_sequence_numbers: bool
    is_free_format: bool = False
    header_comments: list[str] = field(default_factory=list)
    program_id: str = ""
    program_description: str = ""
    program_layer: str = ""
    author: str = ""
    date_written: str = ""
    date_compiled: str = ""
    installation: str = ""
    security: str = ""
    divisions: list[_Division] = field(default_factory=list)
    sections: list[_Section] = field(default_factory=list)
    paragraphs: list[_Paragraph] = field(default_factory=list)
    data_records: list[_DataRecord] = field(default_factory=list)
    copy_references: list[str] = field(default_factory=list)
    lines: list[str] = field(
        default_factory=list
    )  # normalised (seq stripped, continuations joined)
    raw_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Low-level line helpers
# ---------------------------------------------------------------------------


def _decode_source(source_bytes: bytes) -> str:
    """Decode bytes trying UTF-8 → cp1252 → latin-1 (common COBOL encodings)."""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return source_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return source_bytes.decode("latin-1", errors="replace")


def _detect_free_format(raw_lines: list[str]) -> bool:
    """Return True if the source contains a free-format compiler directive."""
    directive = re.compile(r">>\s*SOURCE\s+FORMAT\s+(?:IS\s+)?FREE", re.IGNORECASE)
    return any(directive.search(line) for line in raw_lines[:30])


def _detect_sequence_numbers(raw_lines: list[str]) -> bool:
    """Return True if the majority of non-blank lines start with 6 digits (majority vote)."""
    hits = checked = 0
    for line in raw_lines[:50]:
        if len(line) < 7 or not line.strip():
            continue
        checked += 1
        if re.match(r"^\d{6}", line):
            hits += 1
    if checked == 0:
        return False
    return (hits / checked) >= 0.5


def _strip_sequence(line: str, has_seq: bool) -> str:
    if has_seq and len(line) >= 6 and re.match(r"^\d{6}", line):
        return line[6:]
    return line


def _get_indicator(line: str, has_seq: bool) -> str:
    """Return the COBOL indicator character (column 7 in fixed format).

    After seq stripping: indicator is at position 0.
    Without seq stripping: indicator is at position 6 (after 6 blank seq cols).
    """
    if has_seq:
        return line[0] if line else " "
    return line[6] if len(line) >= 7 else " "


def _is_comment(line: str, has_seq: bool) -> bool:
    """True when the indicator column is ``*`` or ``/``, or the line is a free-format comment."""
    indicator = _get_indicator(line, has_seq)
    if indicator in ("*", "/"):
        return True
    # COBOL 2002 free-format inline comment marker
    return line.lstrip().startswith("*>")


def _join_continuations(lines: list[str], has_seq: bool) -> list[str]:
    """Merge continuation lines (indicator = ``-``) into their predecessors.

    Returns a same-length list; continuation lines become empty strings and
    their Area B content is appended to the nearest non-empty predecessor.
    This lets COPY, CALL, and data-name statements that span two lines be
    matched by a single regex pass.
    """
    result = list(lines)
    for i in range(1, len(result)):
        if _get_indicator(result[i], has_seq) != "-":
            continue
        # Area B content of the continuation line
        if has_seq:
            content = result[i][1:].lstrip()
        else:
            content = result[i][7:].lstrip() if len(result[i]) > 7 else ""
        # Opening quote on a continued literal is suppressed per COBOL spec
        if content.startswith(("'", '"')):
            content = content[1:]
        # Append to the nearest non-empty predecessor
        for j in range(i - 1, -1, -1):
            if result[j]:
                result[j] = result[j].rstrip() + " " + content
                result[i] = ""
                break
    return result


# ---------------------------------------------------------------------------
# Parsing passes
# ---------------------------------------------------------------------------


def _extract_header_comments(parsed: _ParsedCobol) -> None:
    comments: list[str] = []
    for line in parsed.lines:
        stripped = line.strip()
        if stripped.startswith("*>"):
            comments.append(stripped[2:].strip())
        elif stripped.startswith("*"):
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
        if "PROGRAM-ID" not in line.upper():
            continue
        # Handle: PROGRAM-ID. PROGNAME. or PROGRAM-ID. 'PROG-NAME'.
        m = re.search(r"PROGRAM-ID\.?\s+['\"]?([\w-]+)['\"]?", line, re.IGNORECASE)
        if m:
            parsed.program_id = m.group(1).upper()
        elif i + 1 < len(parsed.lines):
            next_line = parsed.lines[i + 1].strip().rstrip(".").strip("'\"")
            parsed.program_id = next_line.upper()
        break


def _extract_divisions(parsed: _ParsedCobol) -> None:
    divisions: list[_Division] = []
    div_pattern = re.compile(
        r"^\s*(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION",
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


def _extract_identification_metadata(parsed: _ParsedCobol) -> None:
    """Extract AUTHOR, DATE-WRITTEN, DATE-COMPILED, INSTALLATION, SECURITY."""
    id_div = next((d for d in parsed.divisions if d.name == "IDENTIFICATION"), None)
    if not id_div:
        return

    lines = parsed.lines
    start = id_div.start_line  # 0-based index into lines
    end = min(id_div.end_line - 1, len(lines))

    meta_map: dict[str, re.Pattern[str]] = {
        "author": re.compile(r"^\s*AUTHOR\.?\s*(.*)", re.IGNORECASE),
        "date_written": re.compile(r"^\s*DATE-WRITTEN\.?\s*(.*)", re.IGNORECASE),
        "date_compiled": re.compile(r"^\s*DATE-COMPILED\.?\s*(.*)", re.IGNORECASE),
        "installation": re.compile(r"^\s*INSTALLATION\.?\s*(.*)", re.IGNORECASE),
        "security": re.compile(r"^\s*SECURITY\.?\s*(.*)", re.IGNORECASE),
    }

    for i in range(start, end):
        line = lines[i]
        if _is_comment(line, parsed.has_sequence_numbers):
            continue
        for attr, pat in meta_map.items():
            if getattr(parsed, attr):  # already collected
                continue
            m = pat.match(line)
            if m:
                value = m.group(1).strip().rstrip(".")
                if not value and i + 1 < end:
                    # Value may be on the next line: AUTHOR.\n    John Smith.
                    value = lines[i + 1].strip().rstrip(".")
                if value:
                    setattr(parsed, attr, value)
                break


def _extract_sections(parsed: _ParsedCobol) -> None:
    """Extract SECTIONs within the PROCEDURE DIVISION as structural groupings."""
    proc_div = next((d for d in parsed.divisions if d.name == "PROCEDURE"), None)
    if not proc_div:
        return

    proc_start = proc_div.start_line  # 0-based index
    proc_end = proc_div.end_line - 1  # exclusive 0-based

    if parsed.has_sequence_numbers:
        sect_re = re.compile(r"^[ \t]{1,4}([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.\s*$", re.IGNORECASE)
    else:
        sect_re = re.compile(r"^[ \t]{1,10}([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.\s*$", re.IGNORECASE)

    decl_re = re.compile(r"^\s*DECLARATIVES\s*\.\s*$", re.IGNORECASE)

    sections: list[_Section] = []
    lines = parsed.lines

    for i in range(proc_start, proc_end):
        line = lines[i] if i < len(lines) else ""
        if _is_comment(line, parsed.has_sequence_numbers):
            continue

        if decl_re.match(line):
            if sections:
                sections[-1].end_line = i + 1
            sections.append(_Section(name="DECLARATIVES", start_line=i + 1))
            continue

        m = sect_re.match(line)
        if not m:
            continue

        sect_name = m.group(1).upper()
        if sections:
            sections[-1].end_line = i + 1
        sections.append(_Section(name=sect_name, start_line=i + 1))

    if sections:
        sections[-1].end_line = proc_div.end_line

    parsed.sections = sections


def _extract_data_records(parsed: _ParsedCobol) -> None:
    """Extract 01-level records and FD/SD entries from the DATA DIVISION."""
    data_div = next((d for d in parsed.divisions if d.name == "DATA"), None)
    if not data_div:
        return

    lines = parsed.lines
    start = data_div.start_line  # 0-based index
    end = min(data_div.end_line - 1, len(lines))

    section_pat = re.compile(
        r"^\s*(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE|COMMUNICATION|REPORT|SCREEN)"
        r"\s+SECTION\s*\.",
        re.IGNORECASE,
    )
    fd_pat = re.compile(r"^[ \t]*(?:FD|SD)[ \t]+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
    # 01 or 1 followed by a name (handles both zero-padded "01" and plain "1")
    rec_pat = re.compile(
        r"^[ \t]*0?1[ \t]+([A-Z0-9][A-Z0-9-]*)(?:[ \t]|\.)",
        re.IGNORECASE,
    )
    pic_pat = re.compile(r"\bPIC(?:TURE)?\b\s+(?:IS\s+)?(\S+)", re.IGNORECASE)

    records: list[_DataRecord] = []
    current_section = "DATA"

    for i in range(start, end):
        line = lines[i]
        if _is_comment(line, parsed.has_sequence_numbers):
            continue

        sm = section_pat.match(line)
        if sm:
            current_section = sm.group(1).upper()
            continue

        # FD/SD — File/Sort description
        fm = fd_pat.match(line)
        if fm:
            name = fm.group(1).upper()
            if records:
                records[-1].end_line = i + 1
            records.append(_DataRecord(name=name, section_name="FILE", start_line=i + 1))
            continue

        # 01-level record
        rm = rec_pat.match(line)
        if rm:
            name = rm.group(1).upper()
            if name == "FILLER":
                continue
            pic = ""
            pm = pic_pat.search(line)
            if pm:
                pic = pm.group(1)
            if records:
                records[-1].end_line = i + 1
            records.append(
                _DataRecord(name=name, section_name=current_section, start_line=i + 1, pic=pic)
            )

    if records:
        records[-1].end_line = end + 1

    parsed.data_records = records


# ---------------------------------------------------------------------------
# Call / PERFORM regex patterns
# ---------------------------------------------------------------------------

_PERFORM_THRU_RE = re.compile(
    r"PERFORM\s+([A-Z0-9][A-Z0-9-]*)\s+(?:THRU|THROUGH)\s+([A-Z0-9][A-Z0-9-]*)",
    re.IGNORECASE,
)
_PERFORM_RE = re.compile(r"PERFORM\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_CALL_RE = re.compile(r"\bCALL\s+['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?", re.IGNORECASE)
_CICS_RE = re.compile(
    r"\bEXEC\s+CICS\s+(?:LINK|XCTL|CALL)\s+PROGRAM\s*\(\s*['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?",
    re.IGNORECASE,
)
_CICS_START_RE = re.compile(
    r"\bEXEC\s+CICS\s+START\s+TRANSID\s*\(\s*['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?",
    re.IGNORECASE,
)

# Words that match the paragraph-name pattern but are NOT paragraph names.
_NOT_PARA_KEYWORDS: frozenset[str] = frozenset(
    {
        # Division / section headers and structural keywords
        "DIVISION",
        "SECTION",
        "DECLARATIVES",
        "END-DECLARATIVES",
        "IDENTIFICATION",
        "ENVIRONMENT",
        "DATA",
        "PROCEDURE",
        # DATA DIVISION section names
        "FILE",
        "LINKAGE",
        "WORKING-STORAGE",
        "LOCAL-STORAGE",
        "REPORT",
        "SCREEN",
        "COMMUNICATION",
        # Common paragraph-body terminators that appear alone on a line
        "END",
        "EXIT",
        "STOP",
        "GOBACK",
        # COBOL OO constructs (COBOL 2002+)
        "CLASS-ID",
        "INTERFACE-ID",
        "METHOD-ID",
        "FACTORY",
    }
)

# PERFORM targets that are actually keywords, not paragraph names
_PERFORM_KEYWORDS: frozenset[str] = frozenset(
    {"UNTIL", "VARYING", "WITH", "THRU", "THROUGH", "TIMES", "TEST", "FOREVER", "INLINE"}
)

# Fixed-format paragraph patterns (see column layout notes in original file)
_PARA_RE_SEQ = re.compile(
    r"^[ \t]{1,4}([A-Z0-9][A-Z0-9-]*)\.\s*$",
    re.IGNORECASE,
)
_PARA_RE_NOSEQ = re.compile(
    r"^[ \t]{1,10}([A-Z0-9][A-Z0-9-]*)\.\s*$",
    re.IGNORECASE,
)
# Free-format: paragraph names conventionally have 0-2 leading spaces; deeper
# indentation (≥3) is reserved for statements so we avoid false positives on
# PERFORM targets that appear alone on an indented line.
_PARA_RE_FREE = re.compile(
    r"^[ \t]{0,2}([A-Z0-9][A-Z0-9-]*)\.\s*$",
    re.IGNORECASE,
)


def _extract_paragraphs(parsed: _ParsedCobol) -> None:
    proc_div = next((d for d in parsed.divisions if d.name == "PROCEDURE"), None)
    if not proc_div:
        return

    proc_start = proc_div.start_line  # 0-based
    proc_end = proc_div.end_line - 1  # exclusive 0-based

    if parsed.is_free_format:
        para_re = _PARA_RE_FREE
    elif parsed.has_sequence_numbers:
        para_re = _PARA_RE_SEQ
    else:
        para_re = _PARA_RE_NOSEQ

    paragraphs: list[_Paragraph] = []
    lines = parsed.lines

    # Build a fast line→section lookup
    def _section_at(line_idx: int) -> str:
        for s in parsed.sections:
            if s.start_line <= line_idx + 1 < s.end_line:
                return s.name
        return ""

    for i in range(proc_start, proc_end):
        line = lines[i] if i < len(lines) else ""
        if _is_comment(line, parsed.has_sequence_numbers):
            continue
        m = para_re.match(line)
        if not m:
            continue
        para_name = m.group(1).upper()
        if para_name in _NOT_PARA_KEYWORDS:
            continue

        # Gather preceding comment block
        comments: list[str] = []
        j = i - 1
        while j >= proc_start - 1:
            prev = lines[j].strip()
            if prev.startswith("*>"):
                comments.insert(0, prev[2:].strip())
                j -= 1
            elif prev.startswith("*"):
                comments.insert(0, prev.lstrip("*").strip())
                j -= 1
            elif not prev:
                j -= 1
            else:
                break

        if paragraphs:
            paragraphs[-1].end_line = i + 1  # 1-based exclusive

        paragraphs.append(
            _Paragraph(
                name=para_name,
                start_line=i + 1,
                comments=comments,
                section=_section_at(i),
            )
        )

    if paragraphs:
        paragraphs[-1].end_line = proc_div.end_line

    # PERFORM / CALL / CICS analysis per paragraph
    for para in paragraphs:
        start_idx = para.start_line - 1
        end_idx = min(para.end_line - 1, len(lines))
        targets: set[str] = set()
        external: set[str] = set()

        for line in lines[start_idx:end_idx]:
            # PERFORM name1 THRU name2 — both are edges
            for mm in _PERFORM_THRU_RE.finditer(line):
                for t in (mm.group(1).upper(), mm.group(2).upper()):
                    if t not in _PERFORM_KEYWORDS:
                        targets.add(t)
            # Plain PERFORM name (also catches the first name of THRU forms, idempotent)
            for mm in _PERFORM_RE.finditer(line):
                target = mm.group(1).upper()
                if target not in _PERFORM_KEYWORDS:
                    targets.add(target)
            for mm in _CALL_RE.finditer(line):
                external.add(f"CALL {mm.group(1).upper()}")
            for mm in _CICS_RE.finditer(line):
                external.add(f"CICS {mm.group(1).upper()}")
            for mm in _CICS_START_RE.finditer(line):
                external.add(f"CICS-START {mm.group(1).upper()}")

        para.perform_targets = sorted(targets)
        para.external_calls = sorted(external)

    parsed.paragraphs = paragraphs


# Improved COPY pattern: handles hyphens in names, quoted names, and IN/OF library syntax
_COPY_RE = re.compile(
    r"\bCOPY\s+['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?"
    r"(?:\s+(?:IN|OF)\s+['\"]?([A-Z0-9][A-Z0-9-]*)['\"]?)?",
    re.IGNORECASE,
)


def _extract_copy_references(parsed: _ParsedCobol) -> None:
    refs: list[str] = []
    sql_include = re.compile(r"\bEXEC\s+SQL\s+INCLUDE\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
    for line in parsed.lines:
        if _is_comment(line, parsed.has_sequence_numbers):
            continue
        for m in _COPY_RE.finditer(line):
            name = m.group(1).upper()
            if name not in refs:
                refs.append(name)
        for m in sql_include.finditer(line):
            ref = f"SQL:{m.group(1).upper()}"
            if ref not in refs:
                refs.append(ref)
    parsed.copy_references = refs


# ---------------------------------------------------------------------------
# Top-level parse function
# ---------------------------------------------------------------------------


def _parse_cobol(source_bytes: bytes, file_path: str) -> _ParsedCobol:
    text = _decode_source(source_bytes)
    raw_lines = text.splitlines()
    is_free = _detect_free_format(raw_lines)
    has_seq = False if is_free else _detect_sequence_numbers(raw_lines)
    lines = [_strip_sequence(line, has_seq) for line in raw_lines]
    if not is_free:
        lines = _join_continuations(lines, has_seq)

    path = Path(file_path)
    suffix = path.suffix.lower().lstrip(".")
    file_type = "cbl" if suffix in ("cbl", "cob", "cobol") else "cpy"

    parsed = _ParsedCobol(
        file_path=file_path,
        file_name=path.name,
        file_type=file_type,
        has_sequence_numbers=has_seq,
        is_free_format=is_free,
        lines=lines,
        raw_lines=raw_lines,
    )
    _extract_header_comments(parsed)
    _extract_program_id(parsed)
    _extract_divisions(parsed)
    _extract_identification_metadata(parsed)
    _extract_sections(parsed)
    _extract_paragraphs(parsed)
    _extract_data_records(parsed)
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

    # Build file-level docstring from header comments + identification metadata
    header_doc = "\n".join(parsed.header_comments) if parsed.header_comments else None
    if parsed.program_description:
        header_doc = (
            (header_doc + "\n\n" + parsed.program_description)
            if header_doc
            else parsed.program_description
        )
    meta_parts: list[str] = []
    if parsed.author:
        meta_parts.append(f"Author: {parsed.author}")
    if parsed.date_written:
        meta_parts.append(f"Date-Written: {parsed.date_written}")
    if parsed.installation:
        meta_parts.append(f"Installation: {parsed.installation}")
    if parsed.security:
        meta_parts.append(f"Security: {parsed.security}")
    if meta_parts:
        meta_str = "\n".join(meta_parts)
        header_doc = (header_doc + "\n\n" + meta_str) if header_doc else meta_str

    # Program-ID as name; fall back to file stem for copybooks without PROGRAM-ID
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

    # One "class" entity per SECTION inside PROCEDURE DIVISION
    for sect in parsed.sections:
        sect_lines = lines[sect.start_line - 1 : sect.end_line - 1]
        sect_source = "\n".join(sect_lines)
        sect_end = min(sect.end_line - 1, total_lines)
        entities.append(
            CodeEntity(
                type="class",
                name=f"{sect.name} SECTION",
                qualified_name=f"{file_path}::{sect.name}_SECTION",
                file_path=file_path,
                start_line=sect.start_line,
                end_line=sect_end,
                source=sect_source,
                parent=f"{file_path}::PROCEDURE_DIVISION",
            )
        )

    # One "class" entity per 01-level data record / FD entry in DATA DIVISION
    for rec in parsed.data_records:
        rec_end_line = min(rec.end_line - 1, total_lines) if rec.end_line else total_lines
        rec_lines = lines[rec.start_line - 1 : rec_end_line]
        rec_source = "\n".join(rec_lines)
        rec_doc = f"PIC {rec.pic}" if rec.pic else None
        entities.append(
            CodeEntity(
                type="class",
                name=rec.name,
                qualified_name=f"{file_path}::{rec.name}",
                file_path=file_path,
                start_line=rec.start_line,
                end_line=rec_end_line,
                source=rec_source,
                docstring=rec_doc,
                parent=f"{file_path}::{rec.section_name}_SECTION",
            )
        )

    # One "function" entity per PARAGRAPH
    for para in parsed.paragraphs:
        para_end = min(para.end_line - 1, total_lines)
        para_lines = lines[para.start_line - 1 : para_end]
        para_source = "\n".join(para_lines)
        doc = "\n".join(para.comments) if para.comments else None
        if para.perform_targets or para.external_calls:
            calls_note = []
            if para.perform_targets:
                calls_note.append("PERFORMS: " + ", ".join(para.perform_targets))
            if para.external_calls:
                calls_note.append("CALLS: " + ", ".join(para.external_calls))
            extra = " | ".join(calls_note)
            doc = (doc + "\n" + extra) if doc else extra

        # Parent is the enclosing section (if any), otherwise the PROCEDURE DIVISION
        parent = (
            f"{file_path}::{para.section}_SECTION"
            if para.section
            else f"{file_path}::PROCEDURE_DIVISION"
        )
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
                parent=parent,
            )
        )

    return entities


# ---------------------------------------------------------------------------
# Call extraction  (PERFORM → paragraph edges)
# ---------------------------------------------------------------------------


def _extract_cobol_calls(entities: list[CodeEntity]) -> list[tuple[str, str, str]]:
    """Return ``(caller_qn, caller_fp, callee_name)`` triples.

    Each PERFORM target becomes a call edge.  The callee_name is the paragraph
    name; the graph store will match it against qualified_names of the form
    ``<file_path>::<PARA_NAME>``.
    """
    results: list[tuple[str, str, str]] = []
    for entity in entities:
        if entity.type != "function":
            continue
        if entity.docstring and "PERFORMS:" in entity.docstring:
            for line in entity.docstring.splitlines():
                if line.startswith("PERFORMS:"):
                    targets_str = line[len("PERFORMS:") :].strip()
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
    name = import_str.removeprefix("SQL:").upper()

    for file_path, file_id in known_files.items():
        normalized = file_path.replace("\\", "/")
        stem = normalized.rsplit("/", 1)[-1]
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
