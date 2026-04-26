"""Prompt loading for the test generator."""

from __future__ import annotations

import logging
import pathlib

logger = logging.getLogger("aquila.test_generator")

_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "reasoning" / "prompts"


def _load_test_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("test prompt file not found: %s", path)
        return ""


def _apply_template(template: str, **kwargs: str) -> str:
    """Replace {key} placeholders without using str.format() (avoids brace conflicts)."""
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", value)
    return template


_PROMPT_PER_FILE = _load_test_prompt("test_per_file")
_PROMPT_PER_MODULE = _load_test_prompt("test_per_module")
_PROMPT_ENTRY_POINTS = _load_test_prompt("test_entry_points")
