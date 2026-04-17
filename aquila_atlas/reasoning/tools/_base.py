"""Shared LLM helper used by multiple tools."""

from __future__ import annotations

from typing import Any


def _llm_complete(llm: Any, model: str, system: str, user: str, max_tokens: int = 3500) -> str:
    """Run a single chat completion and return the response text.

    Returns an error string (not raises) if the model produces no content,
    so callers stay simple.
    """
    response = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    if not content:
        reason = response.choices[0].finish_reason
        return f"No response generated. (finish_reason={reason!r}, model={model!r})"
    return str(content)
