"""CLI application — Typer commands for codetex."""

from __future__ import annotations

import asyncio
import sys
import tomllib
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from codetex_mcp.config.settings import Settings
from codetex_mcp.core import AppContext, create_app
from codetex_mcp.exceptions import CodetexError

app = typer.Typer(name="codetex", add_completion=False)
config_app = typer.Typer(name="config", help="View and update configuration.")
app.add_typer(config_app, name="config")

console = Console()
err_console = Console(stderr=True)


def _run(coro: object) -> object:
    """Run an async coroutine from sync Typer commands."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def _handle_error(exc: CodetexError) -> None:
    """Display a CodetexError and exit with non-zero code."""
    err_console.print(f"Error: {exc}")
    raise typer.Exit(code=1)


async def _get_app() -> AppContext:
    """Create and return the application context."""
    return await create_app()


@app.command()
def add(
    target: str = typer.Argument(help="Remote URL or local path to a git repo"),
) -> None:
    """Clone a remote repo or register a local path."""

    async def _add() -> None:
        ctx = await _get_app()
        try:
            from codetex_mcp.core.repo_manager import _is_remote_url

            if _is_remote_url(target):
                repo = await ctx.repo_manager.add_remote(target)
            else:
                repo = await ctx.repo_manager.add_local(Path(target))
            console.print(f"Added repository '{repo.name}' ({repo.local_path})")
        finally:
            await ctx.db.close()

    try:
        _run(_add())
    except CodetexError as exc:
        _handle_error(exc)


@app.command(name="list")
def list_repos() -> None:
    """List all registered repositories."""

    async def _list() -> None:
        ctx = await _get_app()
        try:
            repos = await ctx.repo_manager.list_repos()
            if not repos:
                console.print("No repositories registered.")
                return

            table = Table(title="Registered Repositories")
            table.add_column("Name", style="bold")
            table.add_column("Remote URL")
            table.add_column("Indexed Commit")
            table.add_column("Last Indexed")

            for repo in repos:
                table.add_row(
                    repo.name,
                    repo.remote_url or "-",
                    repo.indexed_commit[:12] if repo.indexed_commit else "-",
                    repo.last_indexed_at or "-",
                )
            console.print(table)
        finally:
            await ctx.db.close()

    try:
        _run(_list())
    except CodetexError as exc:
        _handle_error(exc)


@app.command()
def status(repo_name: str = typer.Argument(help="Name of the repository")) -> None:
    """Show index status for a repository."""

    async def _status() -> None:
        ctx = await _get_app()
        try:
            repo = await ctx.repo_manager.get_repo(repo_name)
            repo_status = await ctx.context_store.get_repo_status(repo.id)

            # Determine current HEAD and staleness
            current_head: str | None = None
            is_stale = False
            try:
                current_head = await ctx.git.get_head_commit(Path(repo.local_path))
                if repo_status.indexed_commit:
                    is_stale = current_head != repo_status.indexed_commit
            except Exception:
                pass  # git operation may fail if repo dir moved

            table = Table(title=f"Status: {repo.name}")
            table.add_column("Property", style="bold")
            table.add_column("Value")

            table.add_row("Indexed Commit", repo_status.indexed_commit or "Not indexed")
            table.add_row("Current HEAD", current_head or "Unknown")
            table.add_row(
                "Stale",
                "Yes" if is_stale else ("No" if repo_status.indexed_commit else "N/A"),
            )
            table.add_row("Files Indexed", str(repo_status.files_indexed))
            table.add_row("Symbols Indexed", str(repo_status.symbols_indexed))
            table.add_row("Total Tokens", f"{repo_status.total_tokens:,}")
            table.add_row("Last Indexed", repo_status.last_indexed_at or "-")

            console.print(table)
        finally:
            await ctx.db.close()

    try:
        _run(_status())
    except CodetexError as exc:
        _handle_error(exc)


_DEFAULT_TIMEOUT = 1800  # 30 minutes


@app.command()
def index(
    repo_name: str = typer.Argument(help="Name of the repository"),
    path: str | None = typer.Option(
        None, "--path", "-p", help="Restrict to files under this path prefix"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show estimated work without making API calls"
    ),
    timeout: int = typer.Option(
        _DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds before aborting (default 1800)",
    ),
) -> None:
    """Build a full index for a repository."""

    async def _index() -> None:
        ctx = await _get_app()
        try:
            repo = await ctx.repo_manager.get_repo(repo_name)

            if dry_run:
                result = await ctx.indexer.index(repo, path_filter=path, dry_run=True)
                table = Table(title="Dry Run — Index Estimate")
                table.add_column("Metric", style="bold")
                table.add_column("Value")
                table.add_row("Files to index", str(result.files_indexed))
                table.add_row("Symbols found", str(result.symbols_extracted))
                table.add_row("Estimated LLM calls", str(result.llm_calls_made))
                table.add_row("Estimated tokens", f"{result.tokens_used:,}")
                console.print(table)
                return

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TextColumn("[dim]{task.fields[detail]}[/dim]"),
                console=console,
            ) as progress:
                task_id = progress.add_task("Starting...", detail="")

                def on_step(step: str) -> None:
                    progress.update(task_id, description=step, detail="")

                def on_progress(current: int, total: int, file_path: str) -> None:
                    progress.update(
                        task_id,
                        description="Parsing files...",
                        detail=f"{current}/{total}",
                    )

                result = await asyncio.wait_for(
                    ctx.indexer.index(
                        repo,
                        path_filter=path,
                        on_progress=on_progress,
                        on_step=on_step,
                    ),
                    timeout=timeout,
                )

            table = Table(title="Index Complete")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Files indexed", str(result.files_indexed))
            table.add_row("Symbols extracted", str(result.symbols_extracted))
            table.add_row("LLM calls", str(result.llm_calls_made))
            table.add_row("Tokens used", f"{result.tokens_used:,}")
            table.add_row("Duration", f"{result.duration_seconds:.1f}s")
            table.add_row("Commit", result.commit_sha[:12])
            console.print(table)
        except TimeoutError:
            err_console.print(
                f"Error: Indexing timed out after {timeout}s. "
                "Try a smaller --path filter or increase --timeout."
            )
            raise typer.Exit(code=1)
        finally:
            await ctx.db.close()

    try:
        _run(_index())
    except CodetexError as exc:
        _handle_error(exc)


@app.command()
def sync(
    repo_name: str = typer.Argument(help="Name of the repository"),
    path: str | None = typer.Option(
        None, "--path", "-p", help="Restrict to files under this path prefix"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without making API calls"
    ),
    timeout: int = typer.Option(
        _DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds before aborting (default 1800)",
    ),
) -> None:
    """Incremental sync — update index for new commits."""

    async def _sync() -> None:
        ctx = await _get_app()
        try:
            repo = await ctx.repo_manager.get_repo(repo_name)

            if dry_run:
                result = await ctx.syncer.sync(repo, path_filter=path, dry_run=True)
            else:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task_id = progress.add_task("Starting...", total=None)

                    def on_step(step: str) -> None:
                        progress.update(task_id, description=step)

                    result = await asyncio.wait_for(
                        ctx.syncer.sync(repo, path_filter=path, on_step=on_step),
                        timeout=timeout,
                    )

            if result.already_current:
                console.print("Already up to date.")
                return

            title = "Dry Run — Sync Estimate" if dry_run else "Sync Complete"
            table = Table(title=title)
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Files added", str(result.files_added))
            table.add_row("Files modified", str(result.files_modified))
            table.add_row("Files deleted", str(result.files_deleted))
            table.add_row("LLM calls", str(result.llm_calls_made))
            table.add_row("Tokens used", f"{result.tokens_used:,}")
            table.add_row("Tier 1 rebuilt", "Yes" if result.tier1_rebuilt else "No")
            table.add_row(
                "Old commit", result.old_commit[:12] if result.old_commit else "-"
            )
            table.add_row(
                "New commit", result.new_commit[:12] if result.new_commit else "-"
            )
            if not dry_run:
                table.add_row("Duration", f"{result.duration_seconds:.1f}s")
            console.print(table)
        except TimeoutError:
            err_console.print(
                f"Error: Sync timed out after {timeout}s. "
                "Try a smaller --path filter or increase --timeout."
            )
            raise typer.Exit(code=1)
        finally:
            await ctx.db.close()

    try:
        _run(_sync())
    except CodetexError as exc:
        _handle_error(exc)


@app.command()
def context(
    repo_name: str = typer.Argument(help="Name of the repository"),
    file: str | None = typer.Option(
        None, "--file", "-f", help="File path for Tier 2 summary"
    ),
    symbol: str | None = typer.Option(
        None, "--symbol", "-s", help="Symbol name for Tier 3 detail"
    ),
    query: str | None = typer.Option(
        None, "--query", "-q", help="Semantic search query"
    ),
) -> None:
    """Query indexed context — overview, file, symbol, or search."""

    async def _context() -> None:
        ctx = await _get_app()
        try:
            repo = await ctx.repo_manager.get_repo(repo_name)

            if query is not None:
                results = await ctx.search_engine.search(repo.id, query)
                if not results:
                    console.print("No results found.")
                    return
                table = Table(title="Search Results")
                table.add_column("Score", style="dim")
                table.add_column("Kind")
                table.add_column("Path")
                table.add_column("Name", style="bold")
                table.add_column("Summary")
                for r in results:
                    table.add_row(
                        f"{r.score:.4f}",
                        r.kind,
                        r.path,
                        r.name,
                        (r.summary[:80] + "...") if len(r.summary) > 80 else r.summary,
                    )
                console.print(table)
            elif file is not None:
                fc = await ctx.context_store.get_file_context(repo.id, file)
                if fc is None:
                    err_console.print(f"Error: File '{file}' not found in index.")
                    raise typer.Exit(code=1)
                md_parts: list[str] = []
                md_parts.append(f"# {file}")
                if fc.summary:
                    md_parts.append(f"\n{fc.summary}")
                if fc.role:
                    md_parts.append(f"\n**Role:** {fc.role}")
                md_parts.append(f"\n**Lines of code:** {fc.lines_of_code}")
                md_parts.append(f"**Tokens:** {fc.token_count:,}")
                if fc.symbols:
                    md_parts.append("\n## Symbols")
                    for s in fc.symbols:
                        md_parts.append(
                            f"- `{s.signature}` ({s.kind}, L{s.start_line}-{s.end_line})"
                        )
                console.print(Markdown("\n".join(md_parts)))
            elif symbol is not None:
                sd = await ctx.context_store.get_symbol_detail(repo.id, symbol)
                if sd is None:
                    err_console.print(f"Error: Symbol '{symbol}' not found in index.")
                    raise typer.Exit(code=1)
                md_parts = []
                md_parts.append(f"# {sd.signature}")
                md_parts.append(f"\n**File:** {sd.file_path}:{sd.start_line}")
                if sd.summary:
                    md_parts.append(f"\n{sd.summary}")
                if sd.parameters:
                    md_parts.append(f"\n**Parameters:** {sd.parameters}")
                if sd.return_type:
                    md_parts.append(f"**Returns:** {sd.return_type}")
                if sd.calls:
                    md_parts.append(f"**Calls:** {sd.calls}")
                console.print(Markdown("\n".join(md_parts)))
            else:
                overview = await ctx.context_store.get_repo_overview(repo.id)
                if overview is None:
                    console.print("No index found. Run 'codetex index' first.")
                    return
                console.print(Markdown(overview))
        finally:
            await ctx.db.close()

    try:
        _run(_context())
    except CodetexError as exc:
        _handle_error(exc)


@app.command()
def serve() -> None:
    """Start the MCP server (stdio transport)."""
    from codetex_mcp.server.mcp_server import create_server

    server = create_server()
    server.run()


# --- config subcommands ---

_CONFIG_KEY_MAP: dict[str, tuple[str, str]] = {
    "storage.data_dir": ("storage", "data_dir"),
    "llm.provider": ("llm", "provider"),
    "llm.model": ("llm", "model"),
    "llm.api_key": ("llm", "api_key"),
    "indexing.max_file_size_kb": ("indexing", "max_file_size_kb"),
    "indexing.max_concurrent_llm_calls": ("indexing", "max_concurrent_llm_calls"),
    "indexing.tier1_rebuild_threshold": ("indexing", "tier1_rebuild_threshold"),
    "embedding.model": ("embedding", "model"),
}

_INT_KEYS = {"indexing.max_file_size_kb", "indexing.max_concurrent_llm_calls"}
_FLOAT_KEYS = {"indexing.tier1_rebuild_threshold"}


@config_app.command(name="show")
def config_show() -> None:
    """Display current configuration settings."""
    settings = Settings.load()

    table = Table(title="Configuration")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("storage.data_dir", str(settings.data_dir))
    table.add_row("llm.provider", settings.llm_provider)
    table.add_row("llm.model", settings.llm_model)
    table.add_row("llm.api_key", "***" if settings.llm_api_key else "Not set")
    table.add_row("indexing.max_file_size_kb", str(settings.max_file_size_kb))
    table.add_row(
        "indexing.max_concurrent_llm_calls", str(settings.max_concurrent_llm_calls)
    )
    table.add_row(
        "indexing.tier1_rebuild_threshold", str(settings.tier1_rebuild_threshold)
    )
    table.add_row("embedding.model", settings.embedding_model)

    console.print(table)


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(help="Config key (e.g. llm.api_key)"),
    value: str = typer.Argument(help="Value to set"),
) -> None:
    """Set a configuration value in ~/.codetex/config.toml."""
    if key not in _CONFIG_KEY_MAP:
        valid_keys = ", ".join(sorted(_CONFIG_KEY_MAP.keys()))
        err_console.print(
            f"Error: Unknown config key '{key}'. Valid keys: {valid_keys}"
        )
        raise typer.Exit(code=1)

    section, field_name = _CONFIG_KEY_MAP[key]

    # Type-validate numeric keys
    if key in _INT_KEYS:
        try:
            int(value)
        except ValueError:
            err_console.print(f"Error: '{key}' requires an integer value.")
            raise typer.Exit(code=1)
    if key in _FLOAT_KEYS:
        try:
            float(value)
        except ValueError:
            err_console.print(f"Error: '{key}' requires a numeric value.")
            raise typer.Exit(code=1)

    # Load existing TOML or start fresh
    settings = Settings.load()
    config_path = settings.data_dir / "config.toml"

    data: dict[str, dict[str, object]] = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
        # Preserve existing sections
        for k, v in raw.items():
            if isinstance(v, dict):
                data[k] = dict(v)
            else:
                data.setdefault("_root", {})[k] = v

    # Set the value with proper typing
    if section not in data:
        data[section] = {}

    typed_value: object
    if key in _INT_KEYS:
        typed_value = int(value)
    elif key in _FLOAT_KEYS:
        typed_value = float(value)
    else:
        typed_value = value

    data[section][field_name] = typed_value

    # Write TOML manually (tomllib is read-only, no tomli_w in stdlib)
    _write_toml(config_path, data)
    console.print(f"Set {key} = {value}")


def _write_toml(path: Path, data: dict[str, dict[str, object]]) -> None:
    """Write a simple nested dict as TOML."""
    lines: list[str] = []
    for section, values in data.items():
        if section == "_root":
            continue
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, str):
                # Escape backslashes and quotes in string values
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{k} = "{escaped}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            elif isinstance(v, list):
                items = ", ".join(f'"{item}"' for item in v)
                lines.append(f"{k} = [{items}]")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    """Entry point — run the Typer app with top-level error handling."""
    try:
        app()
    except CodetexError as exc:
        err_console.print(f"Error: {exc}")
        sys.exit(1)
