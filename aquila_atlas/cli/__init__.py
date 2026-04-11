"""Aquila-Atlas CLI."""

from __future__ import annotations

import logging

import typer

app = typer.Typer(name="aquila", help="The Atlas of your codebase.")


@app.callback()
def _configure_logging(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="-v info, -vv debug"),
) -> None:
    aquila_level = [logging.WARNING, logging.INFO, logging.DEBUG][min(verbose, 2)]
    logging.basicConfig(
        level=aquila_level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aquila.reasoning").setLevel(aquila_level)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Local folder or file to ingest"),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository ID to store data under"),
) -> None:
    """Parse, chunk, and index a local folder into Neo4j + Qdrant."""
    from aquila_atlas.ingestion import LocalFolderLoader, chunk_files, parse  # noqa: PLC0415
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415

    loader = LocalFolderLoader(path)
    files = list(loader.load())
    if not files:
        typer.echo(f"No source files found at: {path}")
        raise typer.Exit(1)

    typer.echo(f"Source  : {loader.label()}")
    typer.echo(f"Files   : {len(files)}")

    all_entities = []
    for f in files:
        all_entities.extend(parse(f))
    chunks = list(chunk_files(files))

    typer.echo(f"Entities: {len(all_entities)}  Chunks: {len(chunks)}")

    svc = get_knowledge_service()

    typer.echo("Step 1/2 — ingesting graph…", nl=False)
    svc.graph.ingest(repo_id=repo, label=loader.label(), entities=all_entities, commit_sha=None)
    typer.echo(" done.")

    typer.echo("Step 2/2 — embedding vectors…", nl=False)
    svc.ingest_chunks(chunks, repo_id=repo)
    typer.echo(" done.")

    typer.echo(f"\nIngested '{path}' as repo '{repo}'.")


@app.command()
def repos() -> None:
    """List all repo IDs that have been ingested."""
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415

    repo_ids = get_knowledge_service().list_repo_ids()
    if not repo_ids:
        typer.echo("No repos found.")
    else:
        typer.echo("Ingested repos:")
        for rid in repo_ids:
            typer.echo(f"  {rid}")


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


@app.command()
def serve(
    host: str = typer.Option("", "--host", "-H", help="Bind host (overrides API_HOST setting)"),
    port: int = typer.Option(0, "--port", "-p", help="Bind port (overrides API_PORT setting)"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
) -> None:
    """Start the Aquila-Atlas FastAPI server."""
    import uvicorn  # noqa: PLC0415

    from aquila_atlas.config import get_settings  # noqa: PLC0415

    s = get_settings()
    bind_host = host or s.api_host
    bind_port = port or s.api_port
    typer.echo(f"Starting Aquila-Atlas API on http://{bind_host}:{bind_port}")
    uvicorn.run(
        "aquila_atlas.api:app",
        host=bind_host,
        port=bind_port,
        reload=reload,
    )


@app.command()
def chat(
    repo: str = typer.Option(..., "--repo", "-r", help="Repository ID to chat about"),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable token streaming"),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Skip MCP tool loading"),
) -> None:
    """Start an interactive multi-turn chat session about an ingested repository."""
    import asyncio  # noqa: PLC0415

    asyncio.run(_chat_async(repo=repo, no_stream=no_stream, no_mcp=no_mcp))


async def _chat_async(repo: str, no_stream: bool, no_mcp: bool) -> None:
    from aquila_atlas.config import get_settings  # noqa: PLC0415
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415
    from aquila_atlas.reasoning.agent import CodebaseAgent  # noqa: PLC0415

    extra_tools = []
    if not no_mcp:
        try:
            from aquila_atlas.reasoning.tools import get_mcp_tools  # noqa: PLC0415

            extra_tools = await get_mcp_tools(get_settings())
            typer.echo(f"MCP tools: {[t.name for t in extra_tools]}")
        except* Exception as _eg:
            import traceback  # noqa: PLC0415

            typer.echo("MCP unavailable — full trace:", err=True)
            traceback.print_exc()
            typer.echo("Continuing without MCP tools.", err=True)

    service = get_knowledge_service()
    agent = CodebaseAgent(service=service, repo_id=repo, extra_tools=extra_tools or None)

    typer.echo(
        f"Aquila chat — repo: {repo}  (type 'exit' or 'quit' to end, 'reset' to clear history)"
    )
    typer.echo("-" * 60)

    while True:
        try:
            query = typer.prompt("\nYou")
        except (KeyboardInterrupt, EOFError):
            typer.echo("\nGoodbye.")
            break

        query = query.strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            typer.echo("Goodbye.")
            break
        if query.lower() == "reset":
            agent.reset()
            typer.echo("[Conversation history cleared]")
            continue

        typer.echo("\nAquila: ", nl=False)
        if no_stream:
            answer = await agent.achat(query)
            typer.echo(answer)
        else:
            async for token in agent.astream(query):
                typer.echo(token, nl=False)
            typer.echo("")  # newline after streamed response
