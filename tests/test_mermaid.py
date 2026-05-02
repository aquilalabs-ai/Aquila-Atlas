"""Tests for reasoning/mermaid.py — extract, wrap, strip, and validate_with_node."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from aquila_atlas.reasoning.mermaid import (
    _strip_fences,
    extract_mermaid_block,
    validate_with_node,
    wrap_in_fence,
)

# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_mermaid_fence() -> None:
    text = "```mermaid\nflowchart LR\n  A --> B\n```"
    assert _strip_fences(text) == "flowchart LR\n  A --> B"


def test_strip_fences_generic_fence() -> None:
    text = "```\nflowchart TD\n  A --> B\n```"
    assert _strip_fences(text) == "flowchart TD\n  A --> B"


def test_strip_fences_no_fence_returns_unchanged() -> None:
    text = "flowchart LR\n  A --> B"
    assert _strip_fences(text) == text


def test_strip_fences_strips_surrounding_whitespace() -> None:
    text = "  ```\nflowchart LR\n  A --> B\n```  "
    # text.strip() starts with ``` — should be processed
    result = _strip_fences(text.strip())
    assert result == "flowchart LR\n  A --> B"


def test_strip_fences_no_closing_fence_keeps_all_lines() -> None:
    # No closing ```, so end = len(lines) — includes everything after opening fence
    text = "```mermaid\nflowchart LR\n  A --> B"
    result = _strip_fences(text)
    assert "flowchart LR" in result


# ---------------------------------------------------------------------------
# extract_mermaid_block
# ---------------------------------------------------------------------------


def test_extract_explicit_mermaid_fence() -> None:
    text = "Here is the diagram:\n```mermaid\nflowchart LR\n  A --> B\n```\nDone."
    result = extract_mermaid_block(text)
    assert result == "flowchart LR\n  A --> B"


def test_extract_case_insensitive_mermaid_fence() -> None:
    text = "```MERMAID\nflowchart TD\n  X --> Y\n```"
    result = extract_mermaid_block(text)
    assert result == "flowchart TD\n  X --> Y"


def test_extract_plain_fence_known_type_flowchart() -> None:
    text = "```\nflowchart LR\n  A --> B\n```"
    result = extract_mermaid_block(text)
    assert result == "flowchart LR\n  A --> B"


def test_extract_plain_fence_known_type_sequencediagram() -> None:
    text = "```\nsequenceDiagram\n  A->>B: Hello\n```"
    result = extract_mermaid_block(text)
    assert "sequenceDiagram" in result


def test_extract_plain_fence_known_type_classdiagram() -> None:
    text = "```\nclassDiagram\n  class Animal\n```"
    result = extract_mermaid_block(text)
    assert "classDiagram" in result


def test_extract_plain_fence_unknown_type_falls_back_to_full_text() -> None:
    # Fence with non-diagram first word — falls through to full-text fallback
    text = "```python\nsome_code()\n```"
    result = extract_mermaid_block(text)
    # Fallback: strip fences and return stripped text
    assert "some_code()" in result


def test_extract_no_fence_returns_stripped_text() -> None:
    text = "  flowchart LR\n  A --> B  "
    result = extract_mermaid_block(text)
    assert result == "flowchart LR\n  A --> B"


def test_extract_mermaid_fence_takes_priority_over_plain() -> None:
    text = "```\ngraph TD\n  A --> B\n```\n```mermaid\nflowchart LR\n  X --> Y\n```"
    result = extract_mermaid_block(text)
    # Explicit mermaid fence wins
    assert result == "flowchart LR\n  X --> Y"


def test_extract_gantt_diagram() -> None:
    text = "```mermaid\ngantt\n  title My Schedule\n  A: 2024-01-01, 7d\n```"
    result = extract_mermaid_block(text)
    assert result.startswith("gantt")


def test_extract_pie_chart() -> None:
    text = "```\npie\n  title Pets\n  'Dogs': 60\n  'Cats': 40\n```"
    result = extract_mermaid_block(text)
    assert "pie" in result


# ---------------------------------------------------------------------------
# wrap_in_fence
# ---------------------------------------------------------------------------


def test_wrap_in_fence_bare_diagram() -> None:
    diagram = "flowchart LR\n  A --> B"
    result = wrap_in_fence(diagram)
    assert result == "```mermaid\nflowchart LR\n  A --> B\n```"


def test_wrap_in_fence_strips_existing_fences() -> None:
    diagram = "```mermaid\nflowchart LR\n  A --> B\n```"
    result = wrap_in_fence(diagram)
    assert result == "```mermaid\nflowchart LR\n  A --> B\n```"


def test_wrap_in_fence_idempotent_on_wrapped() -> None:
    diagram = "flowchart TD\n  X --> Y"
    once = wrap_in_fence(diagram)
    twice = wrap_in_fence(once)
    assert once == twice


def test_wrap_in_fence_starts_with_mermaid_tag() -> None:
    result = wrap_in_fence("graph LR\n  A --> B")
    assert result.startswith("```mermaid\n")
    assert result.endswith("\n```")


# ---------------------------------------------------------------------------
# validate_with_node — mocked subprocess
# ---------------------------------------------------------------------------


def test_validate_with_node_returns_empty_on_node_not_found() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = validate_with_node("flowchart LR\n  A --> B")
    assert result == []


def test_validate_with_node_returns_empty_list_on_valid_json_valid_true() -> None:
    mock_result = MagicMock()
    mock_result.stdout = '{"valid": true}'
    mock_result.stderr = ""
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = validate_with_node("flowchart LR\n  A --> B")
    assert result == []


def test_validate_with_node_returns_error_on_invalid_diagram() -> None:
    mock_result = MagicMock()
    mock_result.stdout = '{"valid": false, "error": "Parse error at line 1"}'
    mock_result.stderr = ""
    mock_result.returncode = 1
    with patch("subprocess.run", return_value=mock_result):
        result = validate_with_node("baddiagram ???")
    assert len(result) == 1
    assert "Parse error" in result[0]


def test_validate_with_node_returns_error_on_timeout() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=15)):
        result = validate_with_node("flowchart LR\n  A --> B")
    assert result == ["Validation timed out"]


def test_validate_with_node_empty_diagram_returns_error() -> None:
    result = validate_with_node("")
    assert result == ["Diagram is empty"]


def test_validate_with_node_only_whitespace_returns_error() -> None:
    result = validate_with_node("   \n  ")
    assert result == ["Diagram is empty"]


def test_validate_with_node_fenced_diagram_strips_fence() -> None:
    # Fenced input should be stripped before passing to node
    mock_result = MagicMock()
    mock_result.stdout = '{"valid": true}'
    mock_result.stderr = ""
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = validate_with_node("```mermaid\nflowchart LR\n  A --> B\n```")
    assert result == []
    # The argument passed to node should not contain backticks
    call_args = mock_run.call_args[0][0]  # ["node", script_path, diagram_text]
    diagram_arg = call_args[2]
    assert "```" not in diagram_arg


def test_validate_with_node_non_json_stdout_returns_stderr() -> None:
    mock_result = MagicMock()
    mock_result.stdout = "not json at all"
    mock_result.stderr = "node crashed"
    mock_result.returncode = 1
    with patch("subprocess.run", return_value=mock_result):
        result = validate_with_node("flowchart LR\n  A --> B")
    assert "node crashed" in result[0]
