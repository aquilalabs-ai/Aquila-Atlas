"""Neo4j graph store — schema, ingestion, call graph, and traversal queries."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import neo4j

    from aquila_atlas.config import Settings
    from aquila_atlas.ingestion.metadata import CodeEntity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTINS: frozenset[str] = frozenset(
    {
        "print", "len", "range", "str", "int", "list", "dict", "tuple",
        "set", "bool", "type", "super", "isinstance", "issubclass",
        "hasattr", "getattr", "setattr", "delattr", "vars", "dir",
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
        import neo4j  # noqa: PLC0415

        self._driver: neo4j.Driver = neo4j.GraphDatabase.driver(
            uri, auth=(user, password)
        )

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
            # 1. Repository node
            session.execute_write(
                _write_repo,
                repo_id=repo_id,
                label=label,
                commit_sha=commit_sha,
            )

            # 2. File nodes + CONTAINS edges
            if files:
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

            # 3. Class nodes + DEFINES edges
            if classes:
                session.execute_write(
                    _write_classes,
                    rows=[
                        {
                            **_entity_props(
                                e,
                                repo_id,
                                _entity_id(repo_id, e.file_path, e.qualified_name),
                            ),
                            "file_id": _file_id(repo_id, e.file_path),
                        }
                        for e in classes
                    ],
                )

            # 4. Function nodes + DEFINES edges
            if functions:
                session.execute_write(
                    _write_functions,
                    rows=[
                        {
                            **_entity_props(
                                e,
                                repo_id,
                                _entity_id(repo_id, e.file_path, e.qualified_name),
                            ),
                            "file_id": _file_id(repo_id, e.file_path),
                        }
                        for e in functions
                    ],
                )

            # 5. Method nodes + HAS_METHOD edges
            if methods:
                session.execute_write(
                    _write_methods,
                    rows=[
                        {
                            **_entity_props(
                                e,
                                repo_id,
                                _entity_id(repo_id, e.file_path, e.qualified_name),
                            ),
                            "parent_id": _entity_id(repo_id, e.file_path, e.parent)
                            if e.parent
                            else None,
                        }
                        for e in methods
                    ],
                )

            # 6. Import edges
            if files:
                # Build a lookup: file_path → file_id for all ingested files
                known_files: dict[str, str] = {
                    e.file_path: _file_id(repo_id, e.file_path) for e in files
                }
                import_rows: list[dict[str, object]] = []
                unresolved_rows: list[dict[str, object]] = []

                for file_entity in files:
                    unresolved: list[str] = []
                    for imp in file_entity.imports:
                        # Try to match import string to a known file path.
                        # Dotted imports like "aquila_atlas.ingestion.parser"
                        # are translated to path candidates.
                        target_id = _resolve_import(imp, known_files)
                        if target_id is not None:
                            import_rows.append(
                                {
                                    "source_id": _file_id(
                                        repo_id, file_entity.file_path
                                    ),
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
                    session.execute_write(
                        _write_unresolved_imports, rows=unresolved_rows
                    )

            # 7. Call graph edges
            all_callables = functions + methods
            if all_callables:
                known: dict[str, tuple[str, str]] = {
                    e.qualified_name: (
                        _entity_id(repo_id, e.file_path, e.qualified_name),
                        "Function" if e.type == "function" else "Method",
                    )
                    for e in all_callables
                }
                call_triples = extract_calls(all_callables)
                call_rows: list[dict[str, object]] = []
                for caller_qn, caller_fp, callee_name in call_triples:
                    caller_id = _entity_id(repo_id, caller_fp, caller_qn)
                    if callee_name not in known:
                        continue
                    callee_id, _ = known[callee_name]
                    call_rows.append(
                        {"caller_id": caller_id, "callee_id": callee_id}
                    )
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

    Attempts two strategies:
    1. Direct suffix match — ``"aquila_atlas.ingestion.parser"`` →
       ``"aquila_atlas/ingestion/parser.py"``.
    2. Package init match — ``"aquila_atlas.ingestion"`` →
       ``"aquila_atlas/ingestion/__init__.py"``.
    """
    candidate_path = import_str.replace(".", "/") + ".py"
    for file_path, file_id in known_files.items():
        if file_path == candidate_path or file_path.endswith("/" + candidate_path):
            return file_id

    init_path = import_str.replace(".", "/") + "/__init__.py"
    for file_path, file_id in known_files.items():
        if file_path == init_path or file_path.endswith("/" + init_path):
            return file_id

    return None


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_graph_store(settings: Settings | None = None) -> GraphStore:
    """Create a :class:`GraphStore` from application settings."""
    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = settings or get_settings()
    return GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
