"""LangSmith tracing configuration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aquila_atlas.config import Settings


def _configure_langsmith(settings: Settings) -> None:
    """Enable LangSmith tracing if an API key is configured."""
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
