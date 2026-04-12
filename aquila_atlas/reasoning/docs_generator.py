"""AI-powered multi-file documentation generator.

Scopes
------
architecture  — Single comprehensive overview (graph-enriched)
per_module    — One file per top-level package/module (topo-sorted)
per_file      — One file per ingested source file (topo-sorted + graph context)
subsystem     — One file per import-graph community (BFS clustering)
flows         — One file per entry point (call-chain trace)

All scopes support style (technical | functional) and language (ISO-639-1 code).
"""

from __future__ import annotations

import contextlib
import logging
import pathlib
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

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


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"


def _load_docs_prompt(name: str) -> str:
    """Load a docs prompt template from prompts/<name>.md.

    Falls back gracefully to an empty string if the file is missing.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("docs prompt file not found: %s", path)
        return ""


def _apply_template(template: str, **kwargs: str) -> str:
    """Replace {key} placeholders in *template* without using str.format().

    This avoids ValueError when code samples contain literal braces.
    """
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", value)
    return template


# Style descriptions per scope — edit these to change the tone/detail level
# that gets injected into each prompt's {style_description} slot.
_STYLE_DESC: dict[str, dict[str, str]] = {
    "architecture": {
        "technical": "Technical (for developers — include file paths, data flows, dependency graph)",
        "functional": "Functional (for PMs/QA — explain behavior, rules, configuration)",
    },
    "per_module": {
        "technical": "Technical — include class/function signatures, types, integration points",
        "functional": "Functional — explain purpose, behavior, configuration options",
    },
    "per_file": {
        "technical": "Technical — include function/class signatures, parameters, return types, side effects",
        "functional": "Functional — explain what this file does, its rules, and configuration",
    },
    "subsystems": {
        "technical": "Technical — include class/function signatures, integration points, data contracts",
        "functional": "Functional — explain what this subsystem does, its responsibilities, how to use it",
    },
    "flows": {
        "technical": "Technical — include parameters, return types, error handling, side effects at each step",
        "functional": "Functional — explain what happens at each step in plain language, what inputs/outputs are expected",
    },
}

# Loaded once at import time — restart the server to pick up edits.
_PROMPT_ARCHITECTURE = _load_docs_prompt("docs_architecture")
_PROMPT_PER_MODULE = _load_docs_prompt("docs_per_module")
_PROMPT_PER_FILE = _load_docs_prompt("docs_per_file")
_PROMPT_SUBSYSTEMS = _load_docs_prompt("docs_subsystems")
_PROMPT_FLOWS = _load_docs_prompt("docs_flows")

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "zh": "Chinese",
    "ja": "Japanese",
    "pt": "Portuguese",
    "ar": "Arabic",
}

# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _search_context(svc: KnowledgeService, repo_id: str, query: str, top_k: int = 20) -> str:
    results = svc.search(query, repo_id, top_k=top_k)
    if not results:
        return ""
    parts: list[str] = []
    for r in results:
        parts.append(
            f"### {r.file_path}:{r.start_line}-{r.end_line} ({r.chunk_type})\n```\n{r.content}\n```"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------

_DEFAULT_SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Images / media
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".bmp",
        ".tiff",
        ".mp4",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".avi",
        ".mov",
        ".mkv",
        ".webm",
        # Documentation markup
        ".md",
        ".rst",
        ".txt",
        # Compiled / binary artefacts
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".o",
        ".obj",
        ".a",
        ".lib",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".out",
        ".bin",
        ".apk",
        ".app",
        ".wasm",
        ".rlib",
        # Data blobs
        ".csv",
        ".parquet",
        ".feather",
        ".pkl",
        ".pickle",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".db",
        ".sqlite",
        ".npy",
        ".npz",
        ".log",
        # Archives
        ".tar",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        # Misc
        ".lock",
    }
)

# Exact filenames always skipped regardless of exclude_extensions.
_ALWAYS_SKIP_NAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        ".gitignore",
        ".gitattributes",
        ".gitmodules",
        ".editorconfig",
        ".npmrc",
        ".nvmrc",
    }
)


def _list_files(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
) -> list[str]:
    """Return ingested files for *repo_id*, filtered by extension.

    *exclude_extensions* — set of lowercase extensions to skip (e.g. ``{".md", ".png"}``).
    Pass ``None`` to use :data:`_DEFAULT_SKIP_EXTENSIONS`.
    Pass an empty ``frozenset()`` to skip no files based on extension.
    :data:`_ALWAYS_SKIP_NAMES` (git/editor config files) are always removed.
    """
    skip_exts = _DEFAULT_SKIP_EXTENSIONS if exclude_extensions is None else exclude_extensions
    all_files = sorted(svc.list_files(repo_id))

    def _should_skip(path: str) -> bool:
        name = pathlib.Path(path.replace("\\", "/")).name
        ext = pathlib.Path(name).suffix.lower()
        return ext in skip_exts or name in _ALWAYS_SKIP_NAMES

    return [f for f in all_files if not _should_skip(f)]


def _list_modules(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
) -> list[str]:
    files = _list_files(svc, repo_id, exclude_extensions)
    seen: set[str] = set()
    modules: list[str] = []
    for f in files:
        top = f.replace("\\", "/").split("/")[0]
        if top not in seen:
            seen.add(top)
            modules.append(top)
    return modules


def _graph_context_block(svc: KnowledgeService, repo_id: str, file_path: str) -> str:
    """Return a Markdown block describing the graph neighbourhood of *file_path*."""
    ctx = svc.get_file_graph_context(repo_id, file_path)
    if not ctx or (not ctx["imports"] and not ctx["importers"] and not ctx["defines"]):
        return ""
    parts: list[str] = ["**Graph context**"]
    if ctx["in_degree"]:
        parts.append(f"- Imported by **{ctx['in_degree']}** other file(s) (hub score)")
    if ctx["imports"]:
        parts.append("- Imports: " + ", ".join(f"`{p}`" for p in ctx["imports"][:10]))
    if ctx["importers"]:
        parts.append("- Imported by: " + ", ".join(f"`{p}`" for p in ctx["importers"][:10]))
    if ctx["defines"]:
        parts.append("- Defines: " + ", ".join(f"`{s}`" for s in ctx["defines"][:15]))
    return "\n".join(parts)


def _extract_summary(content: str) -> str:
    """Extract the first non-heading paragraph from a Markdown doc as a one-liner."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------


def _topological_sort(files: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Return *files* in dependency order (imported files before importers).

    Files involved in cycles are appended at the end.
    """
    file_set = set(files)
    adj: dict[str, set[str]] = {f: set() for f in files}
    in_degree: dict[str, int] = {f: 0 for f in files}

    for src, tgt in edges:
        if src in file_set and tgt in file_set and tgt not in adj[src]:
            adj[src].add(tgt)
            in_degree[tgt] += 1

    queue: deque[str] = deque(f for f in files if in_degree[f] == 0)
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for dep in sorted(adj[node]):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Append any files not reached (cycles)
    reached = set(ordered)
    ordered.extend(f for f in files if f not in reached)
    return ordered


# ---------------------------------------------------------------------------
# Subsystem / community detection
# ---------------------------------------------------------------------------


def _detect_subsystems(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
) -> list[list[str]]:
    """Group files into subsystems via BFS on the import graph.

    Falls back to top-level directory grouping when no IMPORTS edges exist.
    """
    all_files = _list_files(svc, repo_id, exclude_extensions)
    edges = svc.get_import_graph(repo_id)

    # Build adjacency (undirected for community detection)
    adj: dict[str, set[str]] = {f: set() for f in all_files}
    for src, tgt in edges:
        if src in adj and tgt in adj:
            adj[src].add(tgt)
            adj[tgt].add(src)

    visited: set[str] = set()
    components: list[list[str]] = []
    for start in all_files:
        if start in visited:
            continue
        component: list[str] = []
        queue: deque[str] = deque([start])
        visited.add(start)
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))

    # Fallback: no IMPORTS edges → group by top-level directory
    if all(len(c) == 1 for c in components):
        logger.info(
            "docs_generator: no IMPORTS edges for repo=%s — grouping by top-level directory",
            repo_id,
        )
        by_dir: dict[str, list[str]] = {}
        for f in all_files:
            top = f.replace("\\", "/").split("/")[0]
            by_dir.setdefault(top, []).append(f)
        components = sorted([sorted(v) for v in by_dir.values()], key=lambda c: -len(c))

    return sorted(components, key=lambda c: -len(c))


def _name_subsystem(files: list[str]) -> str:
    """Derive a human-readable subsystem name from common path prefix."""
    if not files:
        return "unknown"
    if len(files) == 1:
        return files[0].replace("\\", "/").split("/")[0]
    parts = [f.replace("\\", "/").split("/") for f in files]
    common: list[str] = []
    for segment_group in zip(*parts, strict=False):
        if len(set(segment_group)) == 1:
            common.append(segment_group[0])
        else:
            break
    return "/".join(common) if common else files[0].split("/")[0]


# ---------------------------------------------------------------------------
# Architecture graph context
# ---------------------------------------------------------------------------


def _build_architecture_graph_context(
    svc: KnowledgeService,
    repo_id: str,
    exclude_extensions: frozenset[str] | None = None,
) -> str:
    """Build a summary of the graph structure for the architecture overview."""
    parts: list[str] = []

    # Most-imported files (hubs)
    edges = svc.get_import_graph(repo_id)
    if edges:
        in_counts: dict[str, int] = {}
        for _, tgt in edges:
            in_counts[tgt] = in_counts.get(tgt, 0) + 1
        hubs = sorted(in_counts.items(), key=lambda x: -x[1])[:10]
        parts.append("**Most-imported files (hubs):**")
        parts.extend(f"- `{f}` — imported by {n} file(s)" for f, n in hubs)

    # Entry points
    entry_points = svc.get_entry_points(repo_id)
    if entry_points:
        parts.append("\n**Entry points (public functions with no callers):**")
        for ep in entry_points[:15]:
            parts.append(f"- `{ep['name']}` in `{ep['file_path']}`")

    # Subsystem summary
    subsystems = _detect_subsystems(svc, repo_id, exclude_extensions)
    if subsystems:
        parts.append("\n**Subsystem clusters:**")
        for sub in subsystems[:8]:
            name = _name_subsystem(sub)
            parts.append(f"- `{name}` — {len(sub)} file(s)")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Per-scope generators
# ---------------------------------------------------------------------------


def _generate_architecture(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    progress_callback and progress_callback(0, 1, "architecture")
    lang_name = _LANGUAGE_NAMES.get(language, "English")
    ctx = _search_context(svc, repo_id, "architecture overview modules components", top_k=20)
    graph_ctx = _build_architecture_graph_context(svc, repo_id, exclude_extensions)
    files = _list_files(svc, repo_id, exclude_extensions)

    file_list = "\n".join(f"- {f}" for f in files[:50])
    if len(files) > 50:
        file_list += "\n..."
    prompt = _apply_template(
        _PROMPT_ARCHITECTURE,
        repo_id=repo_id,
        lang_name=lang_name,
        style_description=_STYLE_DESC["architecture"].get(style, style),
        file_count=str(len(files)),
        file_list=file_list,
        graph_ctx=graph_ctx,
        ctx=ctx,
    )
    result = llm.invoke(prompt)
    content: str = result.content if hasattr(result, "content") else str(result)
    progress_callback and progress_callback(1, 1, None)
    return {"architecture.md": content}


def _generate_per_module(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    modules = _list_modules(svc, repo_id, exclude_extensions)
    all_files = _list_files(svc, repo_id, exclude_extensions)
    edges = svc.get_import_graph(repo_id)

    # Topo-sort at module level
    module_edges: list[tuple[str, str]] = []
    for src, tgt in edges:
        src_mod = src.replace("\\", "/").split("/")[0]
        tgt_mod = tgt.replace("\\", "/").split("/")[0]
        if src_mod != tgt_mod:
            module_edges.append((src_mod, tgt_mod))
    ordered_modules = _topological_sort(modules, module_edges)

    total = len(ordered_modules)
    result: dict[str, str] = {}
    dependency_summaries: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, module in enumerate(ordered_modules):
            progress_callback and progress_callback(i, total, module)
            module_files = [f for f in all_files if f.replace("\\", "/").split("/")[0] == module]
            ctx = _search_context(svc, repo_id, f"module {module} classes functions", top_k=15)

            # Inject summaries from already-generated dependencies
            dep_context = ""
            for src_mod, tgt_mod in module_edges:
                if tgt_mod == module and src_mod in dependency_summaries:
                    dep_context += f"\n**Dependency `{src_mod}`**: {dependency_summaries[src_mod]}"

            prompt = _apply_template(
                _PROMPT_PER_MODULE,
                module=module,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["per_module"].get(style, style),
                file_count=str(len(module_files)),
                module_files="\n".join(f"- {f}" for f in module_files),
                dep_context=dep_context,
                ctx=ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("docs_generator: skipping module %r — LLM error: %s", module, exc)
                content = f"# {module}\n\n> ⚠️ Documentation could not be generated for this module: `{exc}`\n"
            result[f"{module}.md"] = content
            dependency_summaries[module] = _extract_summary(content)
    except GenerationCancelled:
        logger.info(
            "docs_generator: per_module cancelled — returning %d/%d modules", len(result), total
        )
        raise GenerationCancelled(result)

    progress_callback and progress_callback(total, total, None)
    return result


def _generate_per_file(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    files = _list_files(svc, repo_id, exclude_extensions)
    edges = svc.get_import_graph(repo_id)
    ordered = _topological_sort(files, edges)

    total = len(ordered)
    result: dict[str, str] = {}
    dependency_summaries: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, file_path in enumerate(ordered):
            progress_callback and progress_callback(i, total, file_path)
            ctx = _search_context(svc, repo_id, file_path, top_k=10)
            graph_ctx = _graph_context_block(svc, repo_id, file_path)

            # Inject summaries from dependencies already documented
            dep_summaries: list[str] = []
            for src, tgt in edges:
                if src == file_path and tgt in dependency_summaries:
                    dep_summaries.append(f"- `{tgt}`: {dependency_summaries[tgt]}")
            dep_section = (
                ("\n**Already-documented dependencies:**\n" + "\n".join(dep_summaries))
                if dep_summaries
                else ""
            )

            prompt = _apply_template(
                _PROMPT_PER_FILE,
                file_path=file_path,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["per_file"].get(style, style),
                graph_ctx=graph_ctx,
                dep_section=dep_section,
                ctx=ctx,
            )
            try:
                out = llm.invoke(prompt)
                content: str = out.content if hasattr(out, "content") else str(out)
            except Exception as exc:
                logger.warning("docs_generator: skipping file %r — LLM error: %s", file_path, exc)
                content = f"# {file_path}\n\n> ⚠️ Documentation could not be generated for this file: `{exc}`\n"
            doc_path = file_path.replace("\\", "/")
            stem, ext = (
                doc_path.rsplit(".", 1) if "." in doc_path.split("/")[-1] else (doc_path, "")
            )
            if ext and ext not in ("md", "txt", "rst"):
                doc_path = stem + ".md"
            result[doc_path] = content
            dependency_summaries[file_path] = _extract_summary(content)
    except GenerationCancelled:
        logger.info(
            "docs_generator: per_file cancelled — returning %d/%d files", len(result), total
        )
        raise GenerationCancelled(result)

    progress_callback and progress_callback(total, total, None)
    return result


def _generate_subsystems(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    subsystems = _detect_subsystems(svc, repo_id, exclude_extensions)
    total = len(subsystems)
    result: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, files in enumerate(subsystems):
            name = _name_subsystem(files)
            progress_callback and progress_callback(i, total, name)

            # Identify public interface: files with high in-degree
            all_edges = svc.get_import_graph(repo_id)
            in_counts: dict[str, int] = {}
            for _, tgt in all_edges:
                if tgt in files:
                    in_counts[tgt] = in_counts.get(tgt, 0) + 1
            public_files = sorted(in_counts, key=lambda f: -in_counts[f])[:5]

            ctx = _search_context(svc, repo_id, f"subsystem {name} components interface", top_k=15)

            public_files_text = (
                "\n".join(f"- {f} (imported by {in_counts.get(f, 0)} files)" for f in public_files)
                if public_files
                else "(none detected)"
            )
            prompt = _apply_template(
                _PROMPT_SUBSYSTEMS,
                name=name,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["subsystems"].get(style, style),
                file_count=str(len(files)),
                files="\n".join(f"- {f}" for f in files),
                public_files=public_files_text,
                ctx=ctx,
            )
            out = llm.invoke(prompt)
            content: str = out.content if hasattr(out, "content") else str(out)
            result[f"subsystems/{name.replace(chr(92), '/')}.md"] = content
    except GenerationCancelled:
        logger.info(
            "docs_generator: subsystem cancelled — returning %d/%d subsystems", len(result), total
        )
        raise GenerationCancelled(result)

    progress_callback and progress_callback(total, total, None)
    return result


def _generate_flows(
    svc: KnowledgeService,
    repo_id: str,
    style: str,
    language: str,
    llm: Any,
    progress_callback: Callable[[int, int, str | None], None] | None,
    exclude_extensions: frozenset[str] | None = None,
) -> dict[str, str]:
    entry_points = svc.get_entry_points(repo_id)
    if exclude_extensions:
        entry_points = [
            ep
            for ep in entry_points
            if not any(ep["file_path"].lower().endswith(ext) for ext in exclude_extensions)
        ]
    if not entry_points:
        return {
            "flows/no_entry_points.md": "# No entry points found\n\nNo public functions without callers were detected in this repository."
        }

    total = len(entry_points)
    result: dict[str, str] = {}
    lang_name = _LANGUAGE_NAMES.get(language, "English")

    try:
        for i, ep in enumerate(entry_points):
            name = ep["name"]
            file_path = ep["file_path"]
            progress_callback and progress_callback(i, total, name)

            # Build start_id: repo_id:file_path:qualified_name format
            start_id = f"{repo_id}:{file_path}:{name}"
            call_chain: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                call_chain = svc.get_call_chain(repo_id, start_id, max_depth=6)

            # Build call tree text
            tree_lines: list[str] = [f"- `{name}` (depth 0) — entry point in `{file_path}`"]
            for step in call_chain:
                indent = "  " * int(step.get("depth", 1))
                tree_lines.append(
                    f"{indent}- `{step['name']}` (depth {step['depth']}) in `{step['file_path']}`"
                )
            call_tree = "\n".join(tree_lines)

            ctx = _search_context(svc, repo_id, f"function {name} {file_path}", top_k=10)

            prompt = _apply_template(
                _PROMPT_FLOWS,
                name=name,
                file_path=file_path,
                repo_id=repo_id,
                lang_name=lang_name,
                style_description=_STYLE_DESC["flows"].get(style, style),
                call_count=str(len(call_chain)),
                call_tree=call_tree,
                ctx=ctx,
            )
            out = llm.invoke(prompt)
            content: str = out.content if hasattr(out, "content") else str(out)
            doc_dir = file_path.replace("\\", "/").removesuffix(".py")
            safe_func = name.replace(".", "_")
            result[f"flows/{doc_dir}/{safe_func}.md"] = content
    except GenerationCancelled:
        logger.info("docs_generator: flows cancelled — returning %d/%d flows", len(result), total)
        raise GenerationCancelled(result)

    progress_callback and progress_callback(total, total, None)
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


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
