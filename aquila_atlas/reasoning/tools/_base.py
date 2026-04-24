"""Shared LLM helper used by multiple tools."""

from __future__ import annotations

from typing import Any


def _llm_complete(llm: Any, system: str, user: str) -> str:
    """Run a single chat completion via a LangChain BaseChatModel.

    Returns an error string (not raises) if the model produces no content,
    so callers stay simple.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = response.content
    if not content:
        return "No response generated."
    return str(content)
