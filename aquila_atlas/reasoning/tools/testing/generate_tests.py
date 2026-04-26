"""GenerateTestsTool — generate tests for a single file or function on demand."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from aquila_atlas.testing._frameworks import derive_output_path, detect_language, get_framework
from aquila_atlas.testing._helpers import _code_context, _graph_hints
from aquila_atlas.testing._prompts import _PROMPT_ENTRY_POINTS, _PROMPT_PER_FILE, _apply_template

logger = logging.getLogger("aquila.reasoning")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


class GenerateTestsInput(BaseModel):
    target: str = Field(
        description=(
            "File path (e.g. 'src/auth/service.py') or fully-qualified function name "
            "(e.g. 'src/auth/service.py::authenticate_user') to generate tests for."
        )
    )
    repo_id: str = Field(description="Repository ID")


class GenerateTestsTool(BaseTool):
    """Generate test scaffolds for a single file or function using the configured LLM."""

    name: str = "generate_tests"
    description: str = (
        "Generate idiomatic test code for a specific file or function. "
        "Detects the language automatically and chooses the appropriate framework "
        "(pytest, vitest, JUnit 5, etc.). "
        "Pass a file path for file-level tests or 'file_path::function_name' for a "
        "focused test targeting one entry point."
    )
    args_schema: type[BaseModel] = GenerateTestsInput
    service: Any
    llm: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _run(self, target: str, repo_id: str) -> str:
        logger.debug("tool=generate_tests repo=%s target=%r", repo_id, target)
        svc = cast("KnowledgeService", self.service)

        # Detect if target is "file::function" or just a file path
        if "::" in target:
            file_path, function_name = target.split("::", 1)
        else:
            file_path = target
            function_name = None

        language = detect_language(file_path)
        if language is None:
            return (
                f"Cannot determine language for `{file_path}`. "
                "Supported extensions: .py, .ts, .tsx, .js, .jsx, .java, .go, .rs, "
                ".cs, .rb, .kt, .php, .swift, .scala, .sh, .cob, .cbl"
            )

        fw = get_framework(language)
        if fw is None:
            return f"No test framework configured for language: {language}"

        if fw.is_stub:
            return (
                f"COBOL test generation produces comment stubs only.\n\n"
                f"```cobol\n"
                f"      * Test stub for {file_path}\n"
                f"      * TODO: implement with your COBOL test harness.\n"
                f"```"
            )

        code_ctx = _code_context(svc, repo_id, file_path)
        if not code_ctx:
            return f"No code found for `{file_path}` in repo `{repo_id}`."

        imports_block, defines_block = _graph_hints(svc, repo_id, file_path)

        if function_name:
            output_path = derive_output_path(file_path, language)
            # Use entry-points prompt for function-level focus
            results = svc.search(
                f"function {function_name} implementation",
                repo_id,
                top_k=6,
                file_path=file_path,
            )
            fn_ctx = (
                "\n\n".join(
                    f"### {r.qualified_name} ({r.chunk_type})\n```\n{r.content}\n```"
                    for r in results
                )
                or code_ctx
            )

            prompt = _apply_template(
                _PROMPT_ENTRY_POINTS,
                function_name=function_name,
                file_path=file_path,
                repo_id=repo_id,
                language=fw.language_display,
                framework=fw.framework,
                output_path=output_path,
                out_degree="?",
                code_ctx=fn_ctx,
            )
        else:
            output_path = derive_output_path(file_path, language)
            prompt = _apply_template(
                _PROMPT_PER_FILE,
                file_path=file_path,
                repo_id=repo_id,
                language=fw.language_display,
                framework=fw.framework,
                output_path=output_path,
                imports_block=imports_block,
                defines_block=defines_block,
                code_ctx=code_ctx,
            )

        try:
            out = self.llm.invoke(prompt)
            content: str = out.content if hasattr(out, "content") else str(out)
        except Exception as exc:
            logger.warning("generate_tests tool failed for %r: %s", target, exc)
            return f"LLM error while generating tests: {exc}"

        return (
            f"**Generated {fw.framework} tests for `{file_path}`**\n"
            f"*Output path: `{output_path}`*\n\n"
            f"```{language}\n{content.strip()}\n```"
        )
