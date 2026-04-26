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


@app.command(name="tests")
def generate_tests(
    repo: str = typer.Option(..., "--repo", "-r", help="Repository ID"),
    scope: str = typer.Option(
        "per_file",
        "--scope",
        "-s",
        help="per_file | per_module | entry_points",
    ),
    lang: str | None = typer.Option(
        None,
        "--lang",
        "-l",
        help="Comma-separated language filter (e.g. python,typescript). Omit for all languages.",
    ),
    output_dir: str = typer.Option(
        ".",
        "--output-dir",
        "-o",
        help="Directory to write generated test files (default: current directory).",
    ),
) -> None:
    """Generate AI-powered test scaffolds for an ingested repository."""
    import pathlib  # noqa: PLC0415

    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415
    from aquila_atlas.testing import generate_tests as _generate  # noqa: PLC0415

    language_filter: list[str] | None = (
        [item.strip() for item in lang.split(",") if item.strip()] if lang else None
    )

    svc = get_knowledge_service()
    completed_count = 0
    total_count = 0

    def _progress(completed: int, total: int, current: str | None) -> None:
        nonlocal completed_count, total_count
        completed_count = completed
        total_count = total
        if current:
            typer.echo(f"  [{completed}/{total}] {current}", err=False)

    typer.echo(
        f"Generating tests — repo: {repo}  scope: {scope}"
        + (f"  lang: {', '.join(language_filter)}" if language_filter else "")
    )

    try:
        files, _ = _generate(
            svc=svc,
            repo_id=repo,
            scope=scope,  # type: ignore[arg-type]
            language_filter=language_filter,
            progress_callback=_progress,
        )
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not files:
        typer.echo("No test files generated.")
        raise typer.Exit()

    out_root = pathlib.Path(output_dir)
    written = 0
    for rel_path, content in files.items():
        dest = out_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written += 1

    typer.echo(f"\nDone — {written} test file(s) written to '{out_root}'.")


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


@app.command(name="security")
def security(
    repo: str = typer.Option(..., "--repo", "-r", help="Repository ID for context lookup"),
    source: str = typer.Argument(..., help="Local file path or directory to scan"),
    config: str = typer.Option(
        "auto", "--config", "-c", help="Semgrep rule config (default: auto)"
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM triage pass"),
) -> None:
    """Run a security scan on a local file or directory."""
    from aquila_atlas.knowledge.service import get_knowledge_service  # noqa: PLC0415
    from aquila_atlas.security.scanner import scan  # noqa: PLC0415

    _SEV_COLOR = {
        "critical": (typer.colors.RED, True),
        "major": (typer.colors.YELLOW, False),
        "minor": (typer.colors.CYAN, False),
    }
    _SEV_EMOJI = {"critical": "🔴", "major": "🟠", "minor": "🔵"}

    typer.echo(f"Scanning {source!r} for repo '{repo}' …")
    svc = get_knowledge_service()
    try:
        result = scan(
            source=source,
            repo_id=repo,
            svc=svc,
            semgrep_config=config,
            run_llm_triage=not no_llm,
        )
    except Exception as exc:  # noqa: BLE001
        typer.echo(typer.style(f"Scan failed: {exc}", fg=typer.colors.RED, bold=True), err=True)
        raise typer.Exit(1) from exc

    counts = result.severity_counts()
    typer.echo("")

    if not result.findings:
        typer.echo(typer.style("✅  No findings detected.", fg=typer.colors.GREEN, bold=True))
        return

    ordered = sorted(
        result.findings,
        key=lambda f: {"critical": 0, "major": 1, "minor": 2}.get(f.severity, 2),
    )
    for finding in ordered:
        color, bold = _SEV_COLOR.get(finding.severity, (typer.colors.WHITE, False))
        emoji = _SEV_EMOJI.get(finding.severity, "•")
        header = f"{emoji}  {finding.severity.upper()}  {finding.file}:{finding.line}  [{finding.rule_id}]"
        typer.echo(typer.style(header, fg=color, bold=bold))
        typer.echo(f"   OWASP: {finding.owasp_category}")
        typer.echo(f"   {finding.message}")
        if finding.fix_suggestion:
            typer.echo(f"   Fix: {finding.fix_suggestion[:200]}")
        typer.echo("")

    typer.echo("─" * 60)
    typer.echo(
        typer.style(f"🔴 Critical: {counts.get('critical', 0)}", fg=typer.colors.RED, bold=True)
        + "  "
        + typer.style(f"🟠 Major: {counts.get('major', 0)}", fg=typer.colors.YELLOW)
        + "  "
        + typer.style(f"🔵 Minor: {counts.get('minor', 0)}", fg=typer.colors.CYAN)
    )
