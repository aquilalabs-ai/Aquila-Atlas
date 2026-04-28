"""Tests for the reasoning tools layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_mock_settings() -> MagicMock:
    s = MagicMock()
    s.llm_base_url = "http://localhost:11434/v1"
    s.llm_api_key = "ollama"
    s.llm_provider = "ollama"
    s.llm_model = "llama2"
    return s


def test_get_tools_includes_expected_tools() -> None:
    from aquila_atlas.reasoning.tools import get_tools

    class DummyService:
        pass

    svc = DummyService()

    with (
        patch("openai.OpenAI", return_value=MagicMock()),
        patch("aquila_atlas.config.get_settings", return_value=_make_mock_settings()),
    ):
        tools = get_tools(service=svc)

    tool_names = {tool.name for tool in tools}

    expected = {
        # Composite / high-level
        "repo_overview",
        "module_map",
        # Core search and reading
        "semantic_search",
        "file_reader",
        "summarize",
        "generate_docstring",
        "generate_mermaid",
        "validate_mermaid",
        # Graph-traversal
        "list_libs",
        "find_callers",
        "list_entry_points",
        "call_chain",
        # Git (read-only)
        "git_log",
        "git_status",
        "git_diff",
        "git_blame",
        # Test generation
        "generate_tests",
        # Security
        "security_scan",
        "list_security_findings",
    }
    assert tool_names == expected


def test_get_tools_count() -> None:
    """Factory must register exactly 19 tools."""
    from aquila_atlas.reasoning.tools import get_tools

    class DummyService:
        pass

    with (
        patch("openai.OpenAI", return_value=MagicMock()),
        patch("aquila_atlas.config.get_settings", return_value=_make_mock_settings()),
    ):
        tools = get_tools(service=DummyService())

    assert len(tools) == 19
