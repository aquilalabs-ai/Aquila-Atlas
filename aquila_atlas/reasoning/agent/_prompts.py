"""Prompt loading and constants for the LangGraph agent."""

from __future__ import annotations

import logging
import pathlib

logger = logging.getLogger("aquila.reasoning")

# prompts/ is a sibling of the reasoning/ package, i.e. reasoning/prompts/
_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt template from ``prompts/<name>.md``.

    Falls back to an empty string if the file is missing so the agent
    degrades gracefully during development (e.g. before prompts are written).
    """
    path = _PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("prompt file not found: %s", path)
        return ""


# Loaded once at import time — restart the server to pick up edits.
_SYSTEM_PROMPT_BASE = _load_prompt("system_base")
_ROUTER_PROMPT = _load_prompt("router")

_SKILL_MAP: dict[str, str] = {
    "structural": _load_prompt("skill_architecture"),
    "implementation": _load_prompt("skill_implementation"),
    "analysis": _load_prompt("skill_analysis"),
    "generation": _load_prompt("skill_documentation"),
    "diagram": _load_prompt("skill_diagram"),
}

# Human-readable status labels per LangGraph node and LangChain tool name.
_NODE_STATUS: dict[str, str] = {
    "router": "Classifying query...",
    "retrieval": "Searching codebase...",
    "reasoning": "Thinking...",
    "tools": "Running tools...",
}

_TOOL_STATUS: dict[str, str] = {
    "semantic_search": "Semantic search...",
    "graph_traversal": "Traversing dependency graph...",
    "file_reader": "Reading file...",
    "summarize": "Summarizing...",
    "generate_docstring": "Generating docstring...",
    "generate_mermaid": "Generating diagram...",
    "validate_mermaid": "Validating diagram...",
    "get-schema": "Reading graph schema...",
    "read-cypher": "Querying graph...",
    "write-cypher": "Writing to graph...",
    "git_log": "Reading git history...",
    "git_status": "Checking git status...",
    "git_diff": "Computing git diff...",
    "git_blame": "Running git blame...",
}
