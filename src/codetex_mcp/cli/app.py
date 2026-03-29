"""CLI application — Typer commands for codetex."""

from __future__ import annotations

import asyncio
import sys
import tomllib
from pathlib import Path

import typer
from rich.console import Console
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
def add(target: str = typer.Argument(help="Remote URL or local path to a git repo")) -> None:
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
        err_console.print(f"Error: Unknown config key '{key}'. Valid keys: {valid_keys}")
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
