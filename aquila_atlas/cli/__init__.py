"""Aquila-Atlas CLI."""

from __future__ import annotations

import typer

app = typer.Typer(name="aquila", help="The Atlas of your codebase.")


# uv run aquila "how is token-aware chunking implemented" --repo playground-full
@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository ID to search"),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results to return"),
    file: str | None = typer.Option(None, "--file", "-f", help="Filter by file path"),
    chunk_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type: file, class, function, method"
    ),
    language: str | None = typer.Option(
        None, "--lang", "-l", help="Filter by language, e.g. Python"
    ),
) -> None:
    """Search for code semantically across an ingested repository."""
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415

    service = get_knowledge_service()
    results = service.search(
        query=query,
        repo_id=repo,
        top_k=top_k,
        file_path=file,
        chunk_type=chunk_type,
        language=language,
    )

    if not results:
        typer.echo("No results found.")
        raise typer.Exit()

    for i, r in enumerate(results, 1):
        typer.echo(
            f"\n[{i}] {r.file_path}:{r.start_line}-{r.end_line}  ({r.chunk_type})  score={r.score:.4f}"
        )
        typer.echo(f"    {r.qualified_name}  [{r.language}]")
        preview = r.content[:200].replace("\n", " ")
        typer.echo(f"    {preview}{'...' if len(r.content) > 200 else ''}")
