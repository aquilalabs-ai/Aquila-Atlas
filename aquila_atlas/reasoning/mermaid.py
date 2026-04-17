"""Mermaid diagram validation and extraction utilities.

Used by :class:`~aquila_atlas.reasoning.tools.MermaidGeneratorTool` and
:class:`~aquila_atlas.reasoning.tools.ValidateMermaidTool` to ensure
syntactically correct Mermaid output before it reaches the frontend renderer.

Validation is performed by the Node.js ``mermaid_check.js`` script in the
frontend package, which calls ``mermaid.parse()`` — the same parser the
browser uses — so errors are accurate and up-to-date with the installed
Mermaid version.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

logger = logging.getLogger("aquila.reasoning.mermaid")

# Path to the frontend directory (two levels up from this file: reasoning/ → aquila_atlas/ → project root)
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
_NODE_SCRIPT = os.path.join(_FRONTEND_DIR, "src", "mermaid_check.js")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_with_node(diagram: str) -> list[str]:
    """Validate a Mermaid diagram using the Node.js Mermaid parser.

    Runs ``mermaid_check.js`` via Node, which calls ``mermaid.parse()``
    — the canonical parser used by the browser renderer.  No network
    requests are made; the package is resolved from the local
    ``frontend/node_modules``.

    Args:
        diagram: Raw Mermaid diagram text (fences stripped automatically).

    Returns:
        List of human-readable error messages.  Empty list means valid.
    """
    clean = _strip_fences(diagram).strip()
    if not clean:
        return ["Diagram is empty"]

    try:
        result = subprocess.run(
            ["node", _NODE_SCRIPT, clean],
            capture_output=True,
            text=True,
            cwd=_FRONTEND_DIR,
            timeout=15,
        )
    except FileNotFoundError:
        logger.warning("validate_with_node: 'node' not found — skipping validation")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("validate_with_node: Node process timed out")
        return ["Validation timed out"]

    try:
        output = json.loads(result.stdout)
    except Exception:
        error = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        return [error]

    if output.get("valid"):
        return []

    error = output.get("error") or result.stderr.strip() or "Unknown error"
    return [error]


def extract_mermaid_block(text: str) -> str:
    """Extract the first Mermaid diagram from an LLM response.

    Strategy (first match wins):
    1. Fenced ` ```mermaid … ``` ` block
    2. Any fenced ` ``` … ``` ` block whose first word is a known diagram type
    3. The full text stripped of any accidental fences

    Args:
        text: Raw LLM response text.

    Returns:
        The diagram body (no fences, stripped).
    """
    # 1. Explicit ```mermaid fence
    m = re.search(r"```mermaid\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 2. Plain ``` fence — accept if first word looks like a diagram type
    _KNOWN_TYPES = frozenset(
        {
            "flowchart",
            "graph",
            "classdiagram",
            "sequencediagram",
            "erdiagram",
            "statediagram",
            "statediagram-v2",
            "gantt",
            "gitgraph",
            "pie",
            "mindmap",
            "timeline",
            "quadrantchart",
            "requirementdiagram",
            "block-beta",
            "xychart-beta",
            "sankey-beta",
            "architecture-beta",
        }
    )
    m = re.search(r"```[a-z-]*\s*\n(.*?)```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        kw = candidate.split()[0].lower() if candidate else ""
        if kw in _KNOWN_TYPES:
            return candidate

    # 3. Full text (after stripping any accidental fences)
    return _strip_fences(text).strip()


def wrap_in_fence(diagram: str) -> str:
    """Wrap a bare diagram body in ` ```mermaid ``` ` fences."""
    diagram = _strip_fences(diagram).strip()
    return f"```mermaid\n{diagram}\n```"


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
