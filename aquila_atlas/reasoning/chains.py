"""Specialised LangChain chains for focused codebase tasks.

Each chain is a standalone function that answers a specific class of question.
They are intentionally simpler than the full LangGraph agent — no routing, no
multi-turn memory — making them fast and predictable for batch use cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aquila_atlas.config import Settings
    from aquila_atlas.knowledge.service import KnowledgeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm(settings: Settings) -> Any:
    from aquila_atlas.reasoning.llm import get_chat_model  # noqa: PLC0415

    return get_chat_model(settings)


def _search_context(
    query: str,
    repo_id: str,
    service: KnowledgeService,
    top_k: int = 8,
    chunk_type: str | None = None,
) -> str:
    results = service.search(query=query, repo_id=repo_id, top_k=top_k, chunk_type=chunk_type)
    if not results:
        return ""
    parts = [
        f"# {r.file_path}:{r.start_line}-{r.end_line} [{r.chunk_type}]\n{r.content}"
        for r in results
    ]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Code Q&A chain
# ---------------------------------------------------------------------------


def answer_code_question(
    query: str,
    repo_id: str,
    service: KnowledgeService,
    settings: Settings | None = None,
) -> str:
    """Answer a natural-language question about a specific piece of code.

    Args:
        query: Question such as "What does ``VectorStore.search`` do?".
        repo_id: Repository to search within.
        service: Initialised knowledge service.
        settings: Optional settings override.

    Returns:
        Plain-text answer with source citations.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    context = _search_context(query, repo_id, service, top_k=6)
    if not context:
        return f"No relevant code found in repository '{repo_id}'."

    llm = _make_llm(s)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are an expert software engineer. Answer the user's question "
                    "using ONLY the provided code context. Cite file paths and line "
                    "numbers. Be concise and precise."
                )
            ),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"),
        ]
    )
    return str(response.content)


# ---------------------------------------------------------------------------
# Architecture summary chain
# ---------------------------------------------------------------------------


def summarize_architecture(
    repo_id: str,
    service: KnowledgeService,
    settings: Settings | None = None,
    focus: str | None = None,
) -> str:
    """Generate a high-level architecture summary for a repository.

    Args:
        repo_id: Repository to analyse.
        service: Initialised knowledge service.
        settings: Optional settings override.
        focus: Optional sub-area to focus on (e.g. "authentication", "database").

    Returns:
        Markdown-formatted architecture overview.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    query = f"architecture overview {focus or ''} modules packages structure entry points"
    context = _search_context(query, repo_id, service, top_k=12, chunk_type="file")
    if not context:
        return f"No code found in repository '{repo_id}'."

    focus_clause = f" Focus specifically on: {focus}." if focus else ""
    llm = _make_llm(s)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a senior software architect. Analyse the provided code "
                    "context and produce a concise architecture overview in Markdown. "
                    "Cover: main modules/packages, their responsibilities, key data flows, "
                    "and any notable patterns or design decisions."
                )
            ),
            HumanMessage(
                content=(
                    f"Repository: {repo_id}{focus_clause}\n\nCode context:\n{context}\n\n"
                    "Write an architecture overview."
                )
            ),
        ]
    )
    return str(response.content)


# ---------------------------------------------------------------------------
# Refactor suggestion chain
# ---------------------------------------------------------------------------


def suggest_refactor(
    target: str,
    repo_id: str,
    service: KnowledgeService,
    settings: Settings | None = None,
) -> str:
    """Suggest concrete refactoring improvements for a function, class, or file.

    Args:
        target: Qualified name or file path, e.g. ``"VectorStore.search"`` or
            ``"aquila_atlas/knowledge/vector.py"``.
        repo_id: Repository containing the target.
        service: Initialised knowledge service.
        settings: Optional settings override.

    Returns:
        Markdown list of actionable refactoring suggestions.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    context = _search_context(target, repo_id, service, top_k=5)
    if not context:
        return f"Target not found: {target}"

    llm = _make_llm(s)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are an expert Python developer performing a code review. "
                    "Suggest specific, actionable refactoring improvements. "
                    "Cover: readability, performance, testability, error handling, "
                    "and adherence to Python best practices. Format as a Markdown list."
                )
            ),
            HumanMessage(content=f"Review and suggest refactors for: {target}\n\nCode:\n{context}"),
        ]
    )
    return str(response.content)


# ---------------------------------------------------------------------------
# README / doc generation chain
# ---------------------------------------------------------------------------


def generate_readme_section(
    section: str,
    repo_id: str,
    service: KnowledgeService,
    settings: Settings | None = None,
) -> str:
    """Generate a README section for a given topic.

    Args:
        section: Section topic, e.g. ``"Installation"``, ``"API Reference"``,
            ``"Configuration"``, ``"Contributing"``.
        repo_id: Repository to document.
        service: Initialised knowledge service.
        settings: Optional settings override.

    Returns:
        Markdown-formatted README section ready to paste.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    context = _search_context(section, repo_id, service, top_k=8)
    if not context:
        return f"No relevant code found for section: {section}"

    llm = _make_llm(s)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a technical writer generating README documentation. "
                    "Write clear, accurate, developer-friendly Markdown for the "
                    "requested section. Base it strictly on the provided code context. "
                    "Use code blocks, tables, and bullet points where appropriate."
                )
            ),
            HumanMessage(
                content=(
                    f"Repository: {repo_id}\n"
                    f"Section to write: {section}\n\n"
                    f"Code context:\n{context}\n\n"
                    f"Write the '{section}' README section."
                )
            ),
        ]
    )
    return str(response.content)
