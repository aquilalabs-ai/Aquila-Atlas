"""Prompt loading and constants for the documentation generator."""

from __future__ import annotations

import logging
import pathlib

logger = logging.getLogger("aquila.docs_generator")

_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "prompts"


def _load_docs_prompt(name: str) -> str:
    """Load a docs prompt template from prompts/<name>.md.

    Falls back gracefully to an empty string if the file is missing.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("docs prompt file not found: %s", path)
        return ""


def _apply_template(template: str, **kwargs: str) -> str:
    """Replace {key} placeholders in *template* without using str.format().

    This avoids ValueError when code samples contain literal braces.
    """
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", value)
    return template


# Style descriptions per scope — edit these to change the tone/detail level
# that gets injected into each prompt's {style_description} slot.
_STYLE_DESC: dict[str, dict[str, str]] = {
    "architecture": {
        "technical": "Technical (for developers — include file paths, data flows, dependency graph)",
        "functional": "Functional (for PMs/QA — explain behavior, rules, configuration)",
    },
    "per_module": {
        "technical": "Technical — include class/function signatures, types, integration points",
        "functional": "Functional — explain purpose, behavior, configuration options",
    },
    "per_file": {
        "technical": "Technical — include function/class signatures, parameters, return types, side effects",
        "functional": "Functional — explain what this file does, its rules, and configuration",
    },
    "subsystems": {
        "technical": "Technical — include class/function signatures, integration points, data contracts",
        "functional": "Functional — explain what this subsystem does, its responsibilities, how to use it",
    },
    "flows": {
        "technical": "Technical — include parameters, return types, error handling, side effects at each step",
        "functional": "Functional — explain what happens at each step in plain language, what inputs/outputs are expected",
    },
}

# Loaded once at import time — restart the server to pick up edits.
_PROMPT_ARCHITECTURE = _load_docs_prompt("docs_architecture")
_PROMPT_PER_MODULE = _load_docs_prompt("docs_per_module")
_PROMPT_PER_FILE = _load_docs_prompt("docs_per_file")
_PROMPT_SUBSYSTEMS = _load_docs_prompt("docs_subsystems")
_PROMPT_FLOWS = _load_docs_prompt("docs_flows")

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "zh": "Chinese",
    "ja": "Japanese",
    "pt": "Portuguese",
    "ar": "Arabic",
}
