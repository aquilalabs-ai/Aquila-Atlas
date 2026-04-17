"""
PLAYGROUND — Mermaid Validator
==============================
Validate a Mermaid diagram and (optionally) render it to SVG using the
local mermaid-cli installed in frontend/node_modules.

Validation delegates to :func:`aquila_atlas.reasoning.mermaid.validate_with_node`,
which calls the same Node.js ``mermaid.parse()`` engine used by the agent tools.

Run:
    uv run python playground/mermaid/validator.py
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid

from aquila_atlas.reasoning.mermaid import validate_with_node

_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "diagrams")
os.makedirs(_OUTPUT_DIR, exist_ok=True)


def render_svg(diagram_code: str) -> str | None:
    """Render a validated Mermaid diagram to SVG using mermaid-cli.

    Returns the SVG file path on success, or None if rendering fails.
    Assumes ``frontend/node_modules/@mermaid-js/mermaid-cli`` is installed.
    """
    file_id = uuid.uuid4().hex[:10]

    with tempfile.NamedTemporaryFile(suffix=".mmd", delete=False, mode="w", encoding="utf-8") as f:
        f.write(diagram_code)
        input_path = f.name

    svg_path = os.path.join(_OUTPUT_DIR, f"diagram_{file_id}.svg")
    cli = os.path.join(_FRONTEND_DIR, "node_modules/@mermaid-js/mermaid-cli/src/cli.js")

    try:
        proc = subprocess.run(
            ["node", cli, "-i", input_path, "-o", svg_path],
            capture_output=True,
            text=True,
            cwd=_FRONTEND_DIR,
        )
        if proc.returncode != 0:
            print(f"[render] FAILED: {proc.stderr.strip() or 'unknown error'}")
            return None
        return svg_path
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


def validate_and_render(diagram_code: str) -> dict:
    """Validate *diagram_code* and render it to SVG if valid.

    Returns::

        {
            "valid": bool,
            "errors": list[str],   # empty when valid
            "svg_path": str | None
        }
    """
    errors = validate_with_node(diagram_code)
    if errors:
        return {"valid": False, "errors": errors, "svg_path": None}

    svg_path = render_svg(diagram_code)
    return {"valid": True, "errors": [], "svg_path": svg_path}


if __name__ == "__main__":
    samples = [
        # valid
        "graph TD\n  A-->B\n  B-->C",
        # invalid (deliberate syntax error)
        "flowchart TD\n  A --BAD--> B",
    ]

    for i, diagram in enumerate(samples, 1):
        print(f"\n--- Sample {i} ---")
        print(diagram)
        result = validate_and_render(diagram)
        if result["valid"]:
            print(f"[OK] SVG: {result['svg_path']}")
        else:
            print(f"[INVALID] {result['errors']}")
