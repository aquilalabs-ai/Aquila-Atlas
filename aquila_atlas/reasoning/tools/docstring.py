"""DocGenerationTool — generate a Google-style docstring for a function or method."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ._base import _llm_complete

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class DocGenerationInput(BaseModel):
    function_id: str = Field(
        description=(
            "Fully-qualified function or method name, "
            "e.g. 'VectorStore.search' or 'chunker.chunk_file'"
        ),
    )
    repo_id: str = Field(description="Repository ID")


class DocGenerationTool(BaseTool):
    """Generate a Google-style docstring for a function or method."""

    name: str = "generate_docstring"
    description: str = (
        "Generate a detailed Google-style docstring for a function or method. "
        "Describes parameters, return value, and behaviour. "
        "Use this to document undocumented or poorly-documented code."
    )
    args_schema: type[BaseModel] = DocGenerationInput
    service: Any  # KnowledgeService
    llm: Any  # openai.OpenAI

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, function_id: str, repo_id: str) -> str:
        logger.debug("tool=generate_docstring repo=%s id=%r", repo_id, function_id)
        svc = cast("KnowledgeService", self.service)
        results = svc.search(query=function_id, repo_id=repo_id, top_k=3, chunk_type="function")
        if not results:
            results = svc.search(query=function_id, repo_id=repo_id, top_k=3, chunk_type="method")
        if not results:
            return f"Function not found: {function_id}"

        top = results[0]
        return _llm_complete(
            self.llm,
            system=(
                "You are an expert Python developer. "
                "Generate a concise, accurate Google-style docstring for the given function. "
                "Return only the docstring body — no triple quotes, no surrounding code."
            ),
            user=f"Generate a docstring for: {top.qualified_name}\n\nSource code:\n{top.content}",
        )
