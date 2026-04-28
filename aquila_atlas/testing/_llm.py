"""LLM factory for the test generator."""

from __future__ import annotations

from typing import Any


def _make_llm() -> Any:
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.reasoning.llm import get_chat_model  # noqa: PLC0415

    return get_chat_model(get_settings(), temperature=0.1, timeout=600)
