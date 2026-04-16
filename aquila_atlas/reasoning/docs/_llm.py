"""LLM factory for the documentation generator."""

from __future__ import annotations

from typing import Any


def _make_llm() -> Any:
    from langchain_openai import ChatOpenAI  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url or None,
        api_key=SecretStr(s.llm_api_key) if s.llm_api_key else SecretStr("ollama"),
        temperature=0.2,
        # ┌─────────────────────────────────────────────────────────────────┐
        # │  LLM REQUEST TIMEOUT — edit this value to change the per-call   │
        # │  timeout for every documentation generation request.            │
        # │                                                                 │
        # │  Unit: seconds                                                  │
        # │  Default: 300 (5 min)                                           │
        # │  Recommended for large repos / slow models: 600 (10 min)        │
        # │                                                                 │
        # │  Each scope makes one LLM call per file/module/subsystem/flow.  │
        # │  If a single call exceeds this limit the entire job fails.      │
        # └─────────────────────────────────────────────────────────────────┘
        timeout=600,
    )
