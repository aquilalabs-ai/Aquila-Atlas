"""Public entry point for test generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from aquila_atlas.knowledge.service import KnowledgeService

logger = logging.getLogger("aquila.test_generator")

TestScope = Literal["per_file", "per_module", "entry_points"]


class GenerationCancelled(BaseException):
    """Raised by the progress callback when the job is cancelled.

    Each scope generator catches this, attaches partial results, and re-raises.
    """

    def __init__(
        self,
        partial: dict[str, str] | None = None,
        partial_statuses: dict[str, str] | None = None,
    ) -> None:
        super().__init__("Generation cancelled")
        self.partial: dict[str, str] = partial or {}
        self.partial_statuses: dict[str, str] = partial_statuses or {}


def generate_tests(
    svc: KnowledgeService,
    repo_id: str,
    scope: TestScope = "per_file",
    language_filter: list[str] | None = None,
    exclude_extensions: list[str] | None = None,
    progress_callback: Callable[[int, int, str | None], None] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Generate test scaffolds and return ``(files, statuses)`` dicts.

    Args:
        svc: KnowledgeService instance.
        repo_id: Repository to generate tests for.
        scope: One of ``per_file``, ``per_module``, ``entry_points``.
        language_filter: Restrict to specific languages (e.g. ``["python", "typescript"]``).
            Pass ``None`` to generate for all supported languages.
        exclude_extensions: File extensions to skip (e.g. ``[".md", ".png"]``).
            Pass ``None`` to use built-in defaults. Pass ``[]`` to disable filtering.
        progress_callback: Called as ``callback(completed, total, current_target)``.

    Returns:
        A tuple ``(files, statuses)`` where *files* maps output path → test code and
        *statuses* maps output path → one of ``"validated"``, ``"syntax-only"``,
        ``"unvalidated"``.
    """
    from ._llm import _make_llm  # noqa: PLC0415
    from .scopes.entry_points import _generate_entry_points  # noqa: PLC0415
    from .scopes.per_file import _generate_per_file  # noqa: PLC0415
    from .scopes.per_module import _generate_per_module  # noqa: PLC0415

    llm = _make_llm()

    skip: frozenset[str] | None
    if exclude_extensions is None:
        skip = None
    else:
        skip = frozenset(
            (ext if ext.startswith(".") else f".{ext}").lower() for ext in exclude_extensions
        )

    dispatch = {
        "per_file": _generate_per_file,
        "per_module": _generate_per_module,
        "entry_points": _generate_entry_points,
    }

    generator = dispatch.get(scope)
    if generator is None:
        raise ValueError(f"Unknown scope: {scope!r}. Valid: {list(dispatch)}")

    logger.info(
        "test_generator: repo=%s scope=%s lang_filter=%s skip_exts=%s",
        repo_id,
        scope,
        language_filter,
        sorted(skip) if skip is not None else "(defaults)",
    )

    statuses: dict[str, str] = {}
    files = generator(svc, repo_id, language_filter, llm, progress_callback, skip, statuses)
    return files, statuses
