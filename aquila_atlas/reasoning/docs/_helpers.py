"""Shared helpers for the documentation generator."""

from __future__ import annotations

import logging
import pathlib
from collections import deque
from typing import TYPE_CHECKING

logger = logging.getLogger("aquila.docs_generator")

if TYPE_CHECKING:
    from aquila_atlas.knowledge.service import KnowledgeService


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
