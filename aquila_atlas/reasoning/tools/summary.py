"""SummaryTool — summarise a file or class on demand using the configured LLM."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._base import _llm_complete

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class SummaryInput(BaseModel):
    target: str = Field(
        description=(
            "File path (e.g. 'aquila_atlas/config.py') or fully-qualified "
            "class/function name to summarise"
        ),
    )
    repo_id: str = Field(description="Repository ID")


class SummaryTool(BaseTool):
    """Summarise a file or class on demand using the configured LLM."""

    name: str = "summarize"
    description: str = (
        "Generate a plain-English summary of a file, class, or module. "
        "Use this to quickly understand what a component does without reading "
        "every line of code."
    )
    args_schema: type[BaseModel] = SummaryInput
    service: Any  # KnowledgeService
    llm: Any  # openai.OpenAI

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, target: str, repo_id: str) -> str:
        logger.debug("tool=summarize repo=%s target=%r", repo_id, target)
        from aquila_atlas.config import get_settings  # noqa: PLC0415

        svc = cast("KnowledgeService", self.service)
        is_file = "/" in target or target.endswith(".py")
        results = svc.search(
            query=f"summary of {target}",
            repo_id=repo_id,
            top_k=8,
            file_path=target if is_file else None,
        )
        if not results:
            return f"No code found for: {target}"

        code_context = "\n\n".join(
            f"### {r.qualified_name} ({r.chunk_type})\n{r.content}" for r in results
        )
        return _llm_complete(
            self.llm,
            model=get_settings().llm_model,
            system=(
                "You are an expert software engineer. "
                "Summarise the provided code concisely — "
                "what it does, its main responsibilities, and any notable patterns. "
                "Be specific and cite function/class names where relevant."
            ),
            user=f"Summarise: {target}\n\nCode:\n{code_context}",
        )
