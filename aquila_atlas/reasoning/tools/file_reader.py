"""FileReaderTool — fetch the full content of a file from the vector store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class FileReaderInput(BaseModel):
    file_path: str = Field(description="File path relative to the repository root")
    repo_id: str = Field(description="Repository ID")


class FileReaderTool(BaseTool):
    """Fetch the full content of a file from the vector store."""

    name: str = "file_reader"
    description: str = (
        "Retrieve the complete content of a source file. Returns all code "
        "chunks sorted by line number. Use this when you need full file context "
        "rather than just matching snippets."
    )
    args_schema: type[BaseModel] = FileReaderInput
    service: Any  # KnowledgeService

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _MAX_OUTPUT_CHARS: int = 6000

    def _run(self, file_path: str, repo_id: str) -> str:
        logger.debug("tool=file_reader repo=%s path=%r", repo_id, file_path)
        svc = cast("KnowledgeService", self.service)
        # Use the file path as the query so BM25 matches token overlap
        results = svc.search(query=file_path, repo_id=repo_id, top_k=20, file_path=file_path)
        if not results:
            return f"No content found for: {file_path}"

        # Deduplicate by (start_line, end_line) and sort
        seen: set[str] = set()
        chunks = []
        for r in sorted(results, key=lambda x: x.start_line):
            key = f"{r.start_line}:{r.end_line}"
            if key not in seen:
                seen.add(key)
                chunks.append(r)

        header = f"# {file_path}  ({len(chunks)} chunks)\n\n"
        sections = [
            f"# Lines {c.start_line}-{c.end_line} [{c.chunk_type}]\n{c.content}" for c in chunks
        ]
        body = "\n\n---\n\n".join(sections)
        result = header + body
        if len(result) > self._MAX_OUTPUT_CHARS:
            result = (
                result[: self._MAX_OUTPUT_CHARS]
                + f"\n\n[truncated — {len(chunks)} chunks total, showing first {self._MAX_OUTPUT_CHARS} chars]"
            )
        return result
