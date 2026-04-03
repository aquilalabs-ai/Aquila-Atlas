"""Mermaid diagram validation and extraction utilities.

Used by :class:`~aquila_atlas.reasoning.tools.MermaidGeneratorTool` and
:class:`~aquila_atlas.reasoning.tools.ValidateMermaidTool` to ensure
syntactically correct Mermaid output before it reaches the frontend renderer.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("aquila.reasoning.mermaid")

# ---------------------------------------------------------------------------
# Diagram type registry
# ---------------------------------------------------------------------------

# Maps the lowercase first keyword of a diagram declaration to whether it
# *requires* a direction argument (TD / LR / RL / BT / TB).
_DIAGRAM_TYPES: dict[str, bool] = {
    "flowchart": True,
    "graph": True,
    "classdiagram": False,
    "sequencediagram": False,
    "erdiagram": False,
    "statediagram": False,
    "statediagram-v2": False,
    "gantt": False,
    "gitgraph": False,
    "pie": False,
    "mindmap": False,
    "timeline": False,
    "quadrantchart": False,
    "requirementdiagram": False,
    "block-beta": False,
    "xychart-beta": False,
    "sankey-beta": False,
    "architecture-beta": False,
}

_FLOWCHART_DIRECTIONS: frozenset[str] = frozenset({"td", "tb", "lr", "rl", "bt"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_mermaid(diagram: str) -> list[str]:
    """Validate Mermaid diagram syntax.

    Strips ````` ```mermaid ``` ````` fences automatically before checking.

    Args:
        diagram: Raw Mermaid diagram text (fences optional).

    Returns:
        List of human-readable error messages.  Empty list means valid.
    """
    diagram = _strip_fences(diagram).strip()
    if not diagram:
        return ["Diagram is empty"]

    lines = [ln for ln in diagram.splitlines() if ln.strip()]
    if not lines:
        return ["Diagram has no content after stripping blank lines"]

    errors: list[str] = []

    # ── 1. Type declaration (first line) ─────────────────────────────────
    first = lines[0].strip()
    parts = first.split()
    keyword = parts[0].lower() if parts else ""
    needs_direction = _DIAGRAM_TYPES.get(keyword)

    if needs_direction is None:
        known = ", ".join(k if k.endswith("-beta") else k.title() for k in sorted(_DIAGRAM_TYPES))
        errors.append(f"Unknown diagram type {keyword!r}. First line must be one of: {known}")
    elif needs_direction:
        direction = parts[1].lower() if len(parts) > 1 else ""
        if direction not in _FLOWCHART_DIRECTIONS:
            errors.append(
                f"'{keyword}' requires a direction keyword (TD, LR, RL, BT, TB). "
                f"Got: {first!r}. Example: 'flowchart TD'"
            )

    # ── 2. Minimum content ────────────────────────────────────────────────
    content_lines = [ln for ln in lines[1:] if ln.strip()]
    if not content_lines:
        errors.append(
            "Diagram must have at least one node, class, or message after the type declaration"
        )

    # ── 3. Bracket balance (outside quoted strings) ───────────────────────
    # Strip string literals to avoid counting brackets inside them
    bare = re.sub(r'"[^"]*"', '""', diagram)
    bare = re.sub(r"'[^']*'", "''", bare)
    bare = re.sub(r"`[^`]*`", "``", bare)

    for open_c, close_c in (("{", "}"), ("[", "]"), ("(", ")")):
        n_open = bare.count(open_c)
        n_close = bare.count(close_c)
        if n_open != n_close:
            errors.append(
                f"Unbalanced brackets: {n_open}× '{open_c}' vs {n_close}× '{close_c}' — "
                f"check node or class block definitions"
            )

    # ── 4. Type-specific structural checks ────────────────────────────────
    if not errors and keyword in ("flowchart", "graph"):
        _check_flowchart(content_lines, errors)
    elif keyword == "classdiagram":
        _check_class_diagram(content_lines, errors)
    elif keyword == "sequencediagram":
        _check_sequence_diagram(content_lines, errors)

    return errors


def extract_mermaid_block(text: str) -> str:
    """Extract the first Mermaid diagram from an LLM response.

    Strategy (first match wins):
    1. Fenced ` ```mermaid … ``` ` block
    2. Any fenced ` ``` … ``` ` block whose first word is a known diagram type
    3. The full text if it starts with a known diagram type keyword

    Args:
        text: Raw LLM response text.

    Returns:
        The diagram body (no fences, stripped).
    """
    # 1. Explicit ```mermaid fence
    m = re.search(r"```mermaid\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 2. Plain ``` fence whose content looks like a diagram
    m = re.search(r"```[a-z-]*\s*\n(.*?)```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        kw = candidate.split()[0].lower() if candidate else ""
        if kw in _DIAGRAM_TYPES:
            return candidate

    # 3. Full text (after stripping any accidental fences)
    stripped = _strip_fences(text).strip()
    kw = stripped.split()[0].lower() if stripped else ""
    if kw in _DIAGRAM_TYPES:
        return stripped

    return text.strip()


def wrap_in_fence(diagram: str) -> str:
    """Wrap a bare diagram body in ` ```mermaid ``` ` fences."""
    diagram = _strip_fences(diagram).strip()
    return f"```mermaid\n{diagram}\n```"


def validate_with_mermaid_py(diagram: str) -> list[str]:
    """Validate a Mermaid diagram using the mermaid-py library.

    mermaid-py validates by sending the diagram to the Mermaid.ink online API
    (base64-encoded).  If the diagram has syntax errors, the API returns an HTTP
    error and mermaid-py raises ``MermaidError`` with the server's error message.
    Falls back to the built-in Python static validator when the library is not
    installed or the network is unavailable.

    Args:
        diagram: Raw Mermaid diagram text (fences stripped automatically).

    Returns:
        List of human-readable error messages.  Empty list means valid.
    """
    clean = _strip_fences(diagram).strip()
    if not clean:
        return ["Diagram is empty"]

    try:
        import mermaid as md  # noqa: PLC0415
        from mermaid.graph import Graph  # noqa: PLC0415

        # Validation happens during Mermaid.__init__ — it calls mermaid.ink and
        # raises MermaidError if the diagram is syntactically invalid.
        graph = Graph("aquila-diagram", clean)
        md.Mermaid(graph)
        return []

    except ImportError:
        logger.debug("mermaid-py not installed — falling back to Python validator")
        return validate_mermaid(diagram)

    except Exception as exc:
        msg = str(exc).strip()
        if not msg:
            return validate_mermaid(diagram)

        # Extract the most meaningful lines from the mermaid.ink error response.
        lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
        meaningful = [
            ln
            for ln in lines
            if any(
                kw in ln.lower()
                for kw in ("error", "parse", "unexpected", "invalid", "syntax", "expect", "detail")
            )
        ]
        if meaningful:
            return meaningful

        # Network error or other runtime issue — fall back to Python validator.
        python_errors = validate_mermaid(diagram)
        if python_errors:
            return python_errors
        # Last resort: surface the raw exception message.
        return [lines[0]] if lines else [f"Rendering failed: {type(exc).__name__}"]


# ---------------------------------------------------------------------------
# Type-specific validators (internal)
# ---------------------------------------------------------------------------


def _check_flowchart(lines: list[str], errors: list[str]) -> None:
    """Flag class-diagram or sequence-diagram syntax leaked into a flowchart."""
    class_diag_re = re.compile(r"(<\|--)|(--\|>)|(\*--)|(--\*)|( o--)|( --o)")
    for i, raw in enumerate(lines, 2):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if class_diag_re.search(line):
            errors.append(
                f"Line {i}: inheritance/composition arrow found in flowchart "
                f"({line!r}). Use '-->' for directed edges."
            )
        # subgraph end keyword is fine; bare direction keywords are suspicious
        if line.lower() in {"td", "tb", "lr", "rl", "bt"}:
            errors.append(
                f"Line {i}: stray direction keyword {line!r} — "
                f"direction belongs on the first line only."
            )


def _check_class_diagram(lines: list[str], errors: list[str]) -> None:
    """Flag flowchart-syntax edges or bare direction keywords in classDiagram."""
    # Direction keyword on line 2 (common copy-paste mistake)
    if lines and lines[0].strip().upper() in {"TD", "TB", "LR", "RL", "BT"}:
        errors.append(
            f"Line 2: direction keyword {lines[0].strip()!r} is for "
            f"flowchart/graph, not classDiagram — remove it."
        )
    # Flowchart node definitions like `A[text] --> B[text]`
    fc_node_re = re.compile(r"^\w[\w_]*\s*[\[({].*[\])}]\s*(-->|---|-.->|==>)")
    for i, raw in enumerate(lines, 2):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if fc_node_re.match(line):
            errors.append(
                f"Line {i}: looks like flowchart syntax in classDiagram "
                f"({line!r}). Use 'ClassName --> ClassName : label' or "
                f"inheritance arrows like '<|--'."
            )


def _check_sequence_diagram(lines: list[str], errors: list[str]) -> None:
    """Verify a sequenceDiagram has at least one message or participant."""
    valid_starts = (
        "participant",
        "actor",
        "->>",
        "-->>",
        "->",
        "-->",
        "note",
        "loop",
        "alt",
        "opt",
        "else",
        "end",
        "par",
        "critical",
        "break",
        "rect",
        "autonumber",
        "%%",
    )
    has_content = any(
        any(raw.strip().startswith(tok) for tok in valid_starts) for raw in lines if raw.strip()
    )
    if not has_content:
        errors.append(
            "sequenceDiagram has no messages or participants — "
            "add lines like 'participant A' and 'A->>B: message'"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Remove leading/trailing ``` fences (with optional language tag)."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # First line is the opening fence (```mermaid or ```)
    start = 1
    # Last line may be the closing fence
    end = len(lines) - 1 if lines and lines[-1].strip() == "```" else len(lines)
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Programmatic diagram builders
# ---------------------------------------------------------------------------
# These build syntactically correct Mermaid from structured Neo4j data so that
# diagram output is never subject to LLM hallucinations about syntax.

_UNSAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_]")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _mermaid_id(text: str, prefix: str = "n") -> str:
    """Sanitise arbitrary text into a valid Mermaid node/participant identifier.

    Replaces non-alphanumeric characters with underscores, collapses runs,
    strips leading/trailing underscores, and ensures the id starts with a letter.
    Result is capped at 40 characters.
    """
    safe = _UNSAFE_ID_RE.sub("_", text)
    safe = _MULTI_UNDERSCORE_RE.sub("_", safe).strip("_")
    if not safe or not safe[0].isalpha():
        safe = prefix + (safe or "0")
    return safe[:40]


def _short_label(text: str) -> str:
    """Return the last path component of a file path as a short display label."""
    return text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def build_flowchart(
    rows: list[dict[str, Any]],
    direction: str = "TD",
    limit: int = 35,
) -> str:
    """Build a Mermaid ``flowchart`` from Neo4j import-edge rows.

    Expected row keys: ``source`` and ``target`` (file paths).

    The diagram is constructed entirely from Python — no LLM is involved —
    so the output is guaranteed to be syntactically valid.
    """
    nodes: dict[str, str] = {}  # id → label (first-seen wins)
    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    for row in rows[:limit]:
        src = str(row.get("source") or "").strip()
        tgt = str(row.get("target") or "").strip()
        if not src or not tgt:
            continue
        src_id = _mermaid_id(src)
        tgt_id = _mermaid_id(tgt)
        nodes.setdefault(src_id, _short_label(src))
        nodes.setdefault(tgt_id, _short_label(tgt))
        edge = (src_id, tgt_id)
        if edge not in seen_edges:
            seen_edges.add(edge)
            edges.append(edge)

    if not nodes:
        return f"flowchart {direction}\n    NoData[No import edges found]"

    lines: list[str] = [f"flowchart {direction}"]
    for nid, label in nodes.items():
        safe_label = label.replace('"', "'")
        lines.append(f'    {nid}["{safe_label}"]')
    for src_id, tgt_id in edges:
        lines.append(f"    {src_id} --> {tgt_id}")

    return "\n".join(lines)


def build_class_diagram(
    rows: list[dict[str, Any]],
    limit: int = 35,
) -> str:
    """Build a Mermaid ``classDiagram`` from Neo4j class/method rows.

    Expected row keys: ``cls`` (class name), ``file`` (file path),
    ``methods`` (list of method name strings).
    """
    lines: list[str] = ["classDiagram"]

    for row in rows[:limit]:
        cls_name = str(row.get("cls") or "").strip()
        if not cls_name:
            continue
        safe_cls = _UNSAFE_ID_RE.sub("_", cls_name).strip("_") or "Unknown"
        methods: list[Any] = list(row.get("methods") or [])

        lines.append(f"    class {safe_cls} {{")
        for method in methods[:10]:
            m = str(method).strip()
            if m and m.lower() != "none":
                lines.append(f"        +{m}()")
        lines.append("    }")

    if len(lines) == 1:
        lines.append("    class NoClasses")
        lines.append('    note for NoClasses "No classes found in this scope"')

    return "\n".join(lines)


def build_sequence_diagram(
    rows: list[dict[str, Any]],
    limit: int = 35,
) -> str:
    """Build a Mermaid ``sequenceDiagram`` from Neo4j caller/callee rows.

    Expected row keys: ``caller``, ``callee`` (function/method names).
    """
    participants: list[str] = []
    seen_participants: set[str] = set()
    messages: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    for row in rows[:limit]:
        caller = str(row.get("caller") or "").strip()
        callee = str(row.get("callee") or "").strip()
        if not caller or not callee or caller == callee:
            continue
        safe_caller = _mermaid_id(caller, "caller")
        safe_callee = _mermaid_id(callee, "callee")
        if safe_caller not in seen_participants:
            seen_participants.add(safe_caller)
            participants.append(safe_caller)
        if safe_callee not in seen_participants:
            seen_participants.add(safe_callee)
            participants.append(safe_callee)
        edge = (safe_caller, safe_callee)
        if edge not in seen_edges:
            seen_edges.add(edge)
            messages.append(edge)

    lines: list[str] = ["sequenceDiagram"]
    for p in participants:
        lines.append(f"    participant {p}")
    for caller, callee in messages:
        lines.append(f"    {caller}->>{callee}: calls")

    if not participants:
        lines.append("    participant NoData")
        lines.append("    Note over NoData: No call relationships found")

    return "\n".join(lines)
