"""LLM factory for the documentation generator."""

from __future__ import annotations

from typing import Any


def _make_llm() -> Any:
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.reasoning.llm import get_chat_model  # noqa: PLC0415

    return get_chat_model(
        get_settings(),
        temperature=0.2,
        # ┌─────────────────────────────────────────────────────────────────┐
        # │  LLM REQUEST TIMEOUT — edit this value to change the per-call   │
        # │  timeout for every documentation generation request.            │
        # │                                                                 │
        # │  Unit: seconds                                                  │
        # │  Default: 600 (10 min)                                          │
        # │  Each scope makes one LLM call per file/module/subsystem/flow.  │
        # │  If a single call exceeds this limit the entire job fails.      │
        # └─────────────────────────────────────────────────────────────────┘
        timeout=600,
    )
