"""Public entry point for documentation generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

logger = logging.getLogger("aquila.docs_generator")

DocScope = Literal["architecture", "per_module", "per_file", "subsystem", "flows"]


class GenerationCancelled(BaseException):
    """Raised by the progress callback when the job is cancelled.

    Each scope generator catches this, attaches the partial result accumulated
    so far, and re-raises so the caller can persist whatever was completed.
    The ``partial`` attribute holds the files generated before cancellation.
    """

    def __init__(self, partial: dict[str, str] | None = None) -> None:
        super().__init__("Generation cancelled")
        self.partial: dict[str, str] = partial or {}


def generate_docs(
    svc: KnowledgeService,
    repo_id: str,
    scope: DocScope = "architecture",
    style: str = "technical",
    language: str = "en",
    targets: list[str] | None = None,
    exclude_extensions: list[str] | None = None,
    progress_callback: Callable[[int, int, str | None], None] | None = None,
) -> dict[str, str]:
    """Generate documentation and return a ``{filename: markdown}`` dict.

    Args:
        svc: KnowledgeService instance.
        repo_id: Repository to document.
        scope: One of ``architecture``, ``per_module``, ``per_file``, ``subsystem``, ``flows``.
        style: ``technical`` (developer-focused) or ``functional`` (PM/QA-focused).
        language: ISO-639-1 language code (default ``en``).
        targets: Optional list of specific files/modules to document (scope-dependent).
        exclude_extensions: File extensions to skip (e.g. ``[".md", ".png"]``).
            Pass ``None`` to use :data:`_DEFAULT_SKIP_EXTENSIONS`.
            Pass ``[]`` to disable extension-based filtering entirely.
        progress_callback: Called as ``callback(completed, total, current_target)`` for progress.
    """
    from ._llm import _make_llm  # noqa: PLC0415
    from .scopes.architecture import _generate_architecture  # noqa: PLC0415
    from .scopes.flows import _generate_flows  # noqa: PLC0415
    from .scopes.per_file import _generate_per_file  # noqa: PLC0415
    from .scopes.per_module import _generate_per_module  # noqa: PLC0415
    from .scopes.subsystems import _generate_subsystems  # noqa: PLC0415

    llm = _make_llm()

    # Normalise: lowercase, leading dot required, deduplicate.
    skip: frozenset[str] | None
    if exclude_extensions is None:
        skip = None  # sentinel → _list_files uses _DEFAULT_SKIP_EXTENSIONS
    else:
        skip = frozenset(
            (ext if ext.startswith(".") else f".{ext}").lower() for ext in exclude_extensions
        )

    dispatch = {
        "architecture": _generate_architecture,
        "per_module": _generate_per_module,
        "per_file": _generate_per_file,
        "subsystem": _generate_subsystems,
        "flows": _generate_flows,
    }

    generator = dispatch.get(scope)
    if generator is None:
        raise ValueError(f"Unknown scope: {scope!r}. Valid: {list(dispatch)}")

    logger.info(
        "docs_generator: repo=%s scope=%s style=%s language=%s skip_exts=%s",
        repo_id,
        scope,
        style,
        language,
        sorted(skip) if skip is not None else "(defaults)",
    )
    return generator(svc, repo_id, style, language, llm, progress_callback, skip)
