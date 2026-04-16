"""Mermaid block sanitisation and auto-fix helpers for documentation generation."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("aquila.docs_generator")

_MERMAID_FIX_PROMPT = """\
The following Mermaid diagram has syntax errors. Fix ONLY the diagram syntax so it renders correctly.
Return ONLY the corrected diagram inside a ```mermaid fence — no explanation, no other text.

Errors:
{errors}

Diagram to fix:
```mermaid
{diagram}
```
"""

_MERMAID_FENCE_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# Unquoted square-bracket labels containing parens: [Disk (JSON/NBT)]
_UNQUOTED_SQUARE_RE = re.compile(r'\[([^\[\]"]*[()][^\[\]"]*)\]')
# Already-quoted labels that still contain parens: ["foo()"] or ["foo (bar)"]
_QUOTED_LABEL_RE = re.compile(r'(\[")([^"]*[()][^"]*)("\])')
# Stadium nodes whose label contains nested parens: A(foo(bar)) or A(foo())
_STADIUM_NESTED_RE = re.compile(r'(\w[\w.\-]*)(\()([^()]*\([^()]*\)[^()]*|[^()]*\(\)[^()]*)\)')


def _sanitize_mermaid(diagram: str) -> str:
    """Remove / escape parentheses from Mermaid node labels before validation.

    Mermaid uses ``()`` as shape delimiters; any ``()`` nested inside a label
    breaks the parser.  Four passes cover the common LLM mistakes:

    1. Unquoted square-bracket labels with parens → wrap in quotes to preserve text:
       ``[Disk (JSON/NBT)]`` → ``["Disk (JSON/NBT)"]``
    2. Empty ``()`` pairs anywhere (function-call suffixes like ``foo()``).
    3. Already-quoted labels that still have parens: ``["label()"]`` → ``["label"]``.
    4. Nested parens in stadium nodes: ``A(foo(bar))`` → ``A(foo bar)``.
    """
    # 1. Unquoted [label (with parens)] → ["label (with parens)"]
    diagram = _UNQUOTED_SQUARE_RE.sub(lambda m: f'["{m.group(1)}"]', diagram)

    # 2. Remove bare () (e.g. trailing function-call markers)
    diagram = re.sub(r"\(\)", "", diagram)

    # 3. Quoted labels: ["any (text) here"] → ["any text here"]
    def _clean_quoted(m: re.Match[str]) -> str:
        inner = m.group(2).replace("(", "").replace(")", "")
        return f'{m.group(1)}{inner}{m.group(3)}'

    diagram = _QUOTED_LABEL_RE.sub(_clean_quoted, diagram)

    # 4. Stadium nodes with nested parens: ID(label(nested)) → ID(label nested)
    def _clean_stadium(m: re.Match[str]) -> str:
        inner = m.group(3).replace("(", "").replace(")", "")
        return f"{m.group(1)}{m.group(2)}{inner})"

    diagram = _STADIUM_NESTED_RE.sub(_clean_stadium, diagram)

    return diagram


def _fix_mermaid_blocks(content: str, llm: Any) -> str:
    """Find every ```mermaid block in *content*, validate it, and fix any that fail.

    Up to 2 LLM fix attempts are made per block.  If a block cannot be fixed
    it is left unchanged so the document is still usable.
    """
    from aquila_atlas.reasoning.mermaid import (  # noqa: PLC0415
        extract_mermaid_block,
        validate_with_node,
    )

    def _try_fix(diagram: str) -> str:
        """Return a fixed diagram body, or the original if all retries fail."""
        diagram = _sanitize_mermaid(diagram)
        for attempt in range(2):
            errors = validate_with_node(diagram)
            if not errors:
                return diagram
            logger.info(
                "docs_generator: mermaid fix attempt %d — errors: %s", attempt + 1, errors
            )
            fix_prompt = _MERMAID_FIX_PROMPT.replace("{errors}", "\n".join(errors)).replace(
                "{diagram}", diagram
            )
            try:
                resp = llm.invoke(fix_prompt)
                raw: str = resp.content if hasattr(resp, "content") else str(resp)
                diagram = extract_mermaid_block(raw)
            except Exception as exc:
                logger.warning("docs_generator: mermaid fix LLM error: %s", exc)
                break
        # Final validation — keep fixed version if now valid, otherwise revert
        if not validate_with_node(diagram):
            return diagram
        logger.warning("docs_generator: mermaid block could not be fixed — keeping original")
        return diagram  # return best-effort (may still have errors)

    def _replacer(m: re.Match[str]) -> str:
        original_body = m.group(1).strip()
        fixed_body = _try_fix(original_body)
        return f"```mermaid\n{fixed_body}\n```"

    return _MERMAID_FENCE_RE.sub(_replacer, content)
