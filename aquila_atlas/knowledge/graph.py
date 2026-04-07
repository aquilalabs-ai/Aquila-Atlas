"""Neo4j graph store — schema, ingestion, call graph, and traversal queries."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import neo4j

    from aquila_atlas.config import Settings
    from aquila_atlas.ingestion.metadata import CodeEntity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTINS: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "list",
        "dict",
        "tuple",
        "set",
        "bool",
        "type",
        "super",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
    }
)

_CONSTRAINT_STATEMENTS: tuple[str, ...] = (
    "CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT file_id IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
    "CREATE CONSTRAINT method_id IF NOT EXISTS FOR (m:Method) REQUIRE m.id IS UNIQUE",
)

_INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX file_repo_id IF NOT EXISTS FOR (f:File) ON (f.repo_id)",
    "CREATE INDEX function_repo_id IF NOT EXISTS FOR (fn:Function) ON (fn.repo_id)",
    "CREATE INDEX method_repo_id IF NOT EXISTS FOR (m:Method) ON (m.repo_id)",
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _file_id(repo_id: str, file_path: str) -> str:
    return f"{repo_id}:{file_path}"


def _entity_id(repo_id: str, file_path: str, qualified_name: str) -> str:
    return f"{repo_id}:{file_path}:{qualified_name}"


def _entity_props(entity: CodeEntity, repo_id: str, node_id: str) -> dict[str, object]:
    return {
        "id": node_id,
        "repo_id": repo_id,
        "name": entity.name,
        "qualified_name": entity.qualified_name,
        "file_path": entity.file_path,
        "start_line": entity.start_line,
        "end_line": entity.end_line,
        "docstring": entity.docstring,
        "visibility": entity.visibility,
        "is_async": entity.is_async,
        "decorators": list(entity.decorators),
    }


def extract_calls(entities: list[CodeEntity]) -> list[tuple[str, str, str]]:
    """Return ``(caller_qualified_name, caller_file_path, callee_name)`` triples.

    Performs best-effort static analysis by walking ``ast.Call`` nodes inside
    each function/method source.  Only the simple name of the callee is
    extracted — resolution against known entities happens in :meth:`GraphStore.ingest`.
    """
    results: list[tuple[str, str, str]] = []
    for entity in entities:
        if entity.type not in ("function", "method"):
            continue
        try:
            tree = ast.parse(entity.source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                callee = func.id
            elif isinstance(func, ast.Attribute):
                callee = func.attr
            else:
                continue
            if callee in _BUILTINS:
                continue
            results.append((entity.qualified_name, entity.file_path, callee))
    return results


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------


class GraphStore:
    """Synchronous Neo4j graph store for code knowledge graphs."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        import logging  # noqa: PLC0415

        import neo4j  # noqa: PLC0415

        # Suppress schema-warning notifications (e.g. 01N51 "relationship type not in DB")
        # that fire on OPTIONAL MATCH when a rel-type hasn't been created yet.
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        self._driver: neo4j.Driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_constraints(self) -> None:
        """Idempotently create uniqueness constraints and indexes."""
        with self._driver.session() as session:
            for stmt in _CONSTRAINT_STATEMENTS:
                session.run(stmt)
            for stmt in _INDEX_STATEMENTS:
                session.run(stmt)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(
        self,
        repo_id: str,
        label: str,
        entities: list[CodeEntity],
        commit_sha: str | None = None,
    ) -> None:
        """Ingest a list of parsed code entities into the graph.

        Processes nodes in dependency order: Repository → Files → Classes →
        Functions → Methods → Import edges → Call edges.
        """
        self.ensure_constraints()

        files = [e for e in entities if e.type == "file"]
        classes = [e for e in entities if e.type == "class"]
        functions = [e for e in entities if e.type == "function"]
        methods = [e for e in entities if e.type == "method"]

        with self._driver.session() as session:
            self._ingest_repo_node(session, repo_id, label, commit_sha)
            self._ingest_file_nodes(session, repo_id, files)
            self._ingest_class_nodes(session, repo_id, classes)
            self._ingest_function_nodes(session, repo_id, functions)
            self._ingest_method_nodes(session, repo_id, methods)
            self._ingest_import_edges(session, repo_id, files)
            self._ingest_call_edges(session, repo_id, functions + methods)

    # ------------------------------------------------------------------
    # Private ingestion helpers
    # ------------------------------------------------------------------

    def _ingest_repo_node(
        self,
        session: Any,
        repo_id: str,
        label: str,
        commit_sha: str | None,
    ) -> None:
        session.execute_write(_write_repo, repo_id=repo_id, label=label, commit_sha=commit_sha)

    def _ingest_file_nodes(
        self,
        session: Any,
        repo_id: str,
        files: list[CodeEntity],
    ) -> None:
        if not files:
            return
        session.execute_write(
            _write_files,
            repo_id=repo_id,
            rows=[
                {
                    **_entity_props(e, repo_id, _file_id(repo_id, e.file_path)),
                    "unresolved_imports": list(e.imports),
                }
                for e in files
            ],
        )

    def _ingest_class_nodes(
        self,
        session: Any,
        repo_id: str,
        classes: list[CodeEntity],
    ) -> None:
        if not classes:
            return
        session.execute_write(
            _write_classes,
            rows=[
                {
                    **_entity_props(e, repo_id, _entity_id(repo_id, e.file_path, e.qualified_name)),
                    "file_id": _file_id(repo_id, e.file_path),
                }
                for e in classes
            ],
        )

    def _ingest_function_nodes(
        self,
        session: Any,
        repo_id: str,
        functions: list[CodeEntity],
    ) -> None:
        if not functions:
            return
        session.execute_write(
            _write_functions,
            rows=[
                {
                    **_entity_props(e, repo_id, _entity_id(repo_id, e.file_path, e.qualified_name)),
                    "file_id": _file_id(repo_id, e.file_path),
                }
                for e in functions
            ],
        )

    def _ingest_method_nodes(
        self,
        session: Any,
        repo_id: str,
        methods: list[CodeEntity],
    ) -> None:
        if not methods:
            return
        session.execute_write(
            _write_methods,
            rows=[
                {
                    **_entity_props(e, repo_id, _entity_id(repo_id, e.file_path, e.qualified_name)),
                    "parent_id": _entity_id(repo_id, e.file_path, e.parent) if e.parent else None,
                }
                for e in methods
            ],
        )

    def _ingest_import_edges(
        self,
        session: Any,
        repo_id: str,
        files: list[CodeEntity],
    ) -> None:
        if not files:
            return
        known_files: dict[str, str] = {e.file_path: _file_id(repo_id, e.file_path) for e in files}
        import_rows: list[dict[str, object]] = []
        unresolved_rows: list[dict[str, object]] = []

        for file_entity in files:
            unresolved: list[str] = []
            for imp in file_entity.imports:
                target_id = _resolve_import(imp, known_files)
                if target_id is not None:
                    import_rows.append(
                        {
                            "source_id": _file_id(repo_id, file_entity.file_path),
                            "target_id": target_id,
                        }
                    )
                else:
                    unresolved.append(imp)
            if unresolved:
                unresolved_rows.append(
                    {
                        "file_id": _file_id(repo_id, file_entity.file_path),
                        "unresolved_imports": unresolved,
                    }
                )

        if import_rows:
            session.execute_write(_write_import_edges, rows=import_rows)
        if unresolved_rows:
            session.execute_write(_write_unresolved_imports, rows=unresolved_rows)

    def _ingest_call_edges(
        self,
        session: Any,
        repo_id: str,
        callables: list[CodeEntity],
    ) -> None:
        if not callables:
            return
        known: dict[str, tuple[str, str]] = {
            e.qualified_name: (
                _entity_id(repo_id, e.file_path, e.qualified_name),
                "Function" if e.type == "function" else "Method",
            )
            for e in callables
        }
        call_rows: list[dict[str, object]] = [
            {
                "caller_id": _entity_id(repo_id, caller_fp, caller_qn),
                "callee_id": known[callee_name][0],
            }
            for caller_qn, caller_fp, callee_name in extract_calls(callables)
            if callee_name in known
        ]
        if call_rows:
            session.execute_write(_write_call_edges, rows=call_rows)

    # ------------------------------------------------------------------
    # Read queries
    # ------------------------------------------------------------------

    def get_callers(self, function_id: str) -> list[dict[str, object]]:
        """Return nodes that CALL the given function/method."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (caller)-[:CALLS]->(fn)
                WHERE fn.id = $function_id
                RETURN caller
                """,
                function_id=function_id,
            )
            return [dict(record["caller"]) for record in result]

    def get_callees(self, function_id: str) -> list[dict[str, object]]:
        """Return nodes that the given function/method CALLS."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (fn)-[:CALLS]->(callee)
                WHERE fn.id = $function_id
                RETURN callee
                """,
                function_id=function_id,
            )
            return [dict(record["callee"]) for record in result]

    def get_file_imports(self, file_id: str) -> list[dict[str, object]]:
        """Return File nodes that the given file imports."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (f:File)-[:IMPORTS]->(imported:File)
                WHERE f.id = $file_id
                RETURN imported
                """,
                file_id=file_id,
            )
            return [dict(record["imported"]) for record in result]

    def get_file_importers(self, file_id: str) -> list[dict[str, object]]:
        """Return File nodes that import the given file."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (importer:File)-[:IMPORTS]->(f:File)
                WHERE f.id = $file_id
                RETURN importer
                """,
                file_id=file_id,
            )
            return [dict(record["importer"]) for record in result]

    def get_graph(self, repo_id: str) -> dict[str, list[dict[str, object]]]:
        """Return all nodes and edges for a repository (for visualisation).

        Returns a dict with two keys:
        - ``nodes``: list of ``{id, label, properties}`` dicts.
        - ``edges``: list of ``{source, target, type}`` dicts.
        """
        with self._driver.session() as session:
            nodes_result = session.run(
                """
                MATCH (n)
                WHERE n.repo_id = $repo_id OR (n:Repository AND n.id = $repo_id)
                RETURN n, labels(n) AS labels
                """,
                repo_id=repo_id,
            )
            nodes: list[dict[str, object]] = [
                {
                    "id": record["n"]["id"],
                    "label": record["labels"][0] if record["labels"] else "Unknown",
                    "properties": dict(record["n"]),
                }
                for record in nodes_result
            ]

            edges_result = session.run(
                """
                MATCH (src)-[r]->(tgt)
                WHERE (src.repo_id = $repo_id OR (src:Repository AND src.id = $repo_id))
                  AND (tgt.repo_id = $repo_id OR (tgt:Repository AND tgt.id = $repo_id))
                RETURN src.id AS source, type(r) AS rel_type, tgt.id AS target
                """,
                repo_id=repo_id,
            )
            edges: list[dict[str, object]] = [
                {"source": record["source"], "target": record["target"], "type": record["rel_type"]}
                for record in edges_result
            ]

        return {"nodes": nodes, "edges": edges}

    def get_repo_stats(self, repo_id: str) -> dict[str, int]:
        """Return node-type and relationship counts for *repo_id*."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (n)
                WHERE n.repo_id = $repo_id OR (n:Repository AND n.id = $repo_id)
                RETURN labels(n)[0] AS label, count(n) AS cnt
                """,
                repo_id=repo_id,
            )
            counts: dict[str, int] = {record["label"]: record["cnt"] for record in result}

            rel_result = session.run(
                """
                MATCH (src)-[r]->(tgt)
                WHERE (src.repo_id = $repo_id OR (src:Repository AND src.id = $repo_id))
                  AND (tgt.repo_id = $repo_id OR (tgt:Repository AND tgt.id = $repo_id))
                RETURN count(r) AS cnt
                """,
                repo_id=repo_id,
            )
            rel_record = rel_result.single()
            counts["relationships"] = rel_record["cnt"] if rel_record else 0

        return counts

    def delete_repo(self, repo_id: str) -> int:
        """Delete all nodes (and their relationships) for *repo_id*.

        Returns the number of nodes deleted.
        """
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (n)
                WHERE n.repo_id = $repo_id OR (n:Repository AND n.id = $repo_id)
                DETACH DELETE n
                RETURN count(n) AS deleted
                """,
                repo_id=repo_id,
            )
            record = result.single()
            return int(record["deleted"]) if record else 0

    def cypher_read(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute an arbitrary read-only Cypher query and return rows as dicts."""
        with self._driver.session() as session:
            result = session.run(cypher, **(params or {}))
            return [dict(record) for record in result]

    def get_context(self, function_id: str) -> dict[str, object]:
        """Return callers, callees, file, and parent_class for a function/method.

        Uses a single query with OPTIONAL MATCH for each relationship type.
        """
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (fn) WHERE fn.id = $function_id
                OPTIONAL MATCH (caller)-[:CALLS]->(fn)
                OPTIONAL MATCH (fn)-[:CALLS]->(callee)
                OPTIONAL MATCH (f:File)-[:DEFINES]->(fn)
                OPTIONAL MATCH (cls:Class)-[:HAS_METHOD]->(fn)
                RETURN
                    collect(DISTINCT caller) AS callers,
                    collect(DISTINCT callee) AS callees,
                    f AS file,
                    cls AS parent_class
                """,
                function_id=function_id,
            )
            record = result.single()
            if record is None:
                return {
                    "callers": [],
                    "callees": [],
                    "file": None,
                    "parent_class": None,
                }
            return {
                "callers": [dict(n) for n in record["callers"] if n is not None],
                "callees": [dict(n) for n in record["callees"] if n is not None],
                "file": dict(record["file"]) if record["file"] is not None else None,
                "parent_class": dict(record["parent_class"])
                if record["parent_class"] is not None
                else None,
            }


    # ------------------------------------------------------------------
    # Graph-aware documentation helpers
    # ------------------------------------------------------------------

    def get_import_graph(self, repo_id: str) -> list[tuple[str, str]]:
        """Return ``(importer_file_path, imported_file_path)`` for all intra-repo imports."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (src:File {repo_id: $repo_id})-[:IMPORTS]->(tgt:File {repo_id: $repo_id})
                RETURN src.file_path AS src_path, tgt.file_path AS tgt_path
                """,
                repo_id=repo_id,
            )
            return [(record["src_path"], record["tgt_path"]) for record in result]

    def get_file_graph_context(self, repo_id: str, file_path: str) -> dict[str, Any]:
        """Return graph neighbourhood for a file: imports, importers, in_degree, symbols."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (f:File {repo_id: $repo_id, file_path: $file_path})
                OPTIONAL MATCH (f)-[:IMPORTS]->(imp:File)
                OPTIONAL MATCH (importer:File)-[:IMPORTS]->(f)
                OPTIONAL MATCH (f)-[:DEFINES]->(sym)
                RETURN
                    collect(DISTINCT imp.file_path) AS imports,
                    collect(DISTINCT importer.file_path) AS importers,
                    collect(DISTINCT sym.qualified_name) AS defines
                """,
                repo_id=repo_id,
                file_path=file_path,
            )
            record = result.single()
            if record is None:
                return {"imports": [], "importers": [], "defines": [], "in_degree": 0}
            imports = [p for p in record["imports"] if p is not None]
            importers = [p for p in record["importers"] if p is not None]
            return {
                "imports": imports,
                "importers": importers,
                "defines": [s for s in record["defines"] if s is not None],
                "in_degree": len(importers),
            }

    def get_entry_points(self, repo_id: str) -> list[dict[str, Any]]:
        """Return public functions/methods with no incoming CALLS edges (entry points)."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (fn {repo_id: $repo_id})
                WHERE (fn:Function OR fn:Method)
                  AND fn.visibility = 'public'
                  AND NOT EXISTS { MATCH ()-[:CALLS]->(fn) }
                RETURN fn.qualified_name AS name, fn.file_path AS file_path,
                       labels(fn)[0] AS kind
                ORDER BY fn.file_path, fn.qualified_name
                LIMIT 30
                """,
                repo_id=repo_id,
            )
            return [dict(record) for record in result]

    def get_call_chain(
        self, repo_id: str, start_id: str, max_depth: int = 6
    ) -> list[dict[str, Any]]:
        """BFS via CALLS edges up to *max_depth* hops from *start_id*."""
        with self._driver.session() as session:
            depth = max(1, min(max_depth, 10))
            result = session.run(
                f"""
                MATCH path = (start)-[:CALLS*1..{depth}]->(callee)
                WHERE start.id = $start_id AND callee.repo_id = $repo_id
                RETURN callee.qualified_name AS name,
                       callee.file_path AS file_path,
                       length(path) AS depth
                ORDER BY depth, callee.file_path
                """,
                start_id=start_id,
                repo_id=repo_id,
            )
            return [dict(record) for record in result]


# ---------------------------------------------------------------------------
# Private Cypher transaction functions
# ---------------------------------------------------------------------------


def _write_repo(
    tx: neo4j.ManagedTransaction,
    repo_id: str,
    label: str,
    commit_sha: str | None,
) -> None:
    tx.run(
        """
        MERGE (r:Repository {id: $id})
        SET r.label = $label, r.commit_sha = $commit_sha
        """,
        id=repo_id,
        label=label,
        commit_sha=commit_sha,
    )


def _write_files(
    tx: neo4j.ManagedTransaction,
    repo_id: str,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (f:File {id: row.id})
        SET f += row
        WITH f, row
        MATCH (r:Repository {id: $repo_id})
        MERGE (r)-[:CONTAINS]->(f)
        """,
        rows=rows,
        repo_id=repo_id,
    )


def _write_classes(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (c:Class {id: row.id})
        SET c += row
        WITH c, row
        MATCH (f:File {id: row.file_id})
        MERGE (f)-[:DEFINES]->(c)
        """,
        rows=rows,
    )


def _write_functions(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (fn:Function {id: row.id})
        SET fn += row
        WITH fn, row
        MATCH (f:File {id: row.file_id})
        MERGE (f)-[:DEFINES]->(fn)
        """,
        rows=rows,
    )


def _write_methods(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (m:Method {id: row.id})
        SET m += row
        WITH m, row
        WHERE row.parent_id IS NOT NULL
        MATCH (cls:Class {id: row.parent_id})
        MERGE (cls)-[:HAS_METHOD]->(m)
        """,
        rows=rows,
    )


def _write_import_edges(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (src:File {id: row.source_id})
        MATCH (tgt:File {id: row.target_id})
        MERGE (src)-[:IMPORTS]->(tgt)
        """,
        rows=rows,
    )


def _write_unresolved_imports(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (f:File {id: row.file_id})
        SET f.unresolved_imports = row.unresolved_imports
        """,
        rows=rows,
    )


def _write_call_edges(
    tx: neo4j.ManagedTransaction,
    rows: list[dict[str, object]],
) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (caller) WHERE caller.id = row.caller_id
        MATCH (callee) WHERE callee.id = row.callee_id
        MERGE (caller)-[:CALLS]->(callee)
        """,
        rows=rows,
    )


# ---------------------------------------------------------------------------
# Import resolution helper
# ---------------------------------------------------------------------------


def _resolve_import(import_str: str, known_files: dict[str, str]) -> str | None:
    """Try to map a dotted import string to a known file ID.

    Works regardless of whether the repo was ingested from the package root
    (paths like ``aquila_atlas/ingestion/parser.py``) or from inside the package
    (paths like ``ingestion/parser.py`` when the loader root was the package dir).

    For each candidate shape (module.py and package/__init__.py) we check:
    - exact match
    - candidate ends with stored path  (stored path is a suffix — repo rooted deeper)
    - stored path ends with candidate  (candidate is a suffix — import has package prefix)
    """

    def _match(candidate: str) -> str | None:
        for file_path, file_id in known_files.items():
            if (
                file_path == candidate
                or candidate.endswith("/" + file_path)
                or file_path.endswith("/" + candidate)
            ):
                return file_id
        return None

    return _match(import_str.replace(".", "/") + ".py") or _match(
        import_str.replace(".", "/") + "/__init__.py"
    )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_graph_store(settings: Settings | None = None) -> GraphStore:
    """Create a :class:`GraphStore` from application settings."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    return GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
