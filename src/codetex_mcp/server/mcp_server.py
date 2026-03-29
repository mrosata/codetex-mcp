"""MCP server — stdio transport with 7 tools for LLM code context.

See architecture doc §3.2 and §6 for tool signatures and response shapes.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from codetex_mcp.core import AppContext, create_app
from codetex_mcp.exceptions import CodetexError, NoIndexError

_app_ctx: AppContext | None = None


async def _get_ctx() -> AppContext:
    """Return the shared AppContext, creating it on first call."""
    global _app_ctx  # noqa: PLW0603
    if _app_ctx is None:
        _app_ctx = await create_app()
    return _app_ctx


def create_server() -> FastMCP:
    """Create and return the FastMCP server instance with all tools registered."""
    server = FastMCP("codetex")

    @server.tool()
    async def get_repo_overview(repo_name: str) -> str:
        """Return the Tier 1 markdown overview for a repository.

        Includes repository purpose, directory structure, key technologies,
        entry points, and architecture patterns.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)
            overview = await ctx.context_store.get_repo_overview(repo.id)
            if overview is None:
                raise NoIndexError(
                    f"Repository '{repo_name}' has no index. "
                    "Run 'codetex index' first."
                )
            return overview
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def get_file_context(repo_name: str, file_path: str) -> str:
        """Return the Tier 2 file summary for a specific file.

        Includes file purpose, public interfaces, dependencies,
        role classification, line count, and token count.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)
            fc = await ctx.context_store.get_file_context(repo.id, file_path)
            if fc is None:
                raise ValueError(
                    f"File '{file_path}' not found in index for "
                    f"repository '{repo_name}'."
                )
            parts: list[str] = [f"# {file_path}"]
            if fc.summary:
                parts.append(f"\n{fc.summary}")
            if fc.role:
                parts.append(f"\n**Role:** {fc.role}")
            parts.append(f"\n**Lines of code:** {fc.lines_of_code}")
            parts.append(f"**Tokens:** {fc.token_count:,}")
            if fc.symbols:
                parts.append("\n## Symbols")
                for s in fc.symbols:
                    parts.append(
                        f"- `{s.signature}` ({s.kind}, L{s.start_line}-{s.end_line})"
                    )
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def get_symbol_detail(repo_name: str, symbol_name: str) -> str:
        """Return the Tier 3 detail for a specific symbol.

        Includes full signature, description, parameters with types,
        return type, call relationships, and file location.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)
            sd = await ctx.context_store.get_symbol_detail(repo.id, symbol_name)
            if sd is None:
                raise ValueError(
                    f"Symbol '{symbol_name}' not found in index for "
                    f"repository '{repo_name}'."
                )
            parts: list[str] = [f"# {sd.signature}"]
            parts.append(f"\n**File:** {sd.file_path}:{sd.start_line}")
            if sd.summary:
                parts.append(f"\n{sd.summary}")
            if sd.parameters:
                parts.append(f"\n**Parameters:** {sd.parameters}")
            if sd.return_type:
                parts.append(f"**Returns:** {sd.return_type}")
            if sd.calls:
                parts.append(f"**Calls:** {sd.calls}")
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def search_context(
        repo_name: str, query: str, max_results: int = 10
    ) -> str:
        """Search for relevant code context using semantic similarity.

        Returns a ranked list of matching files and symbols with
        relevance scores.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)
            results = await ctx.search_engine.search(
                repo.id, query, max_results=max_results
            )
            if not results:
                return "No results found."
            parts: list[str] = ["# Search Results", ""]
            parts.append("| Score | Kind | Path | Name | Summary |")
            parts.append("|-------|------|------|------|---------|")
            for r in results:
                summary = r.summary
                if len(summary) > 80:
                    summary = summary[:80] + "..."
                parts.append(
                    f"| {r.score:.4f} | {r.kind} | {r.path} | {r.name} | {summary} |"
                )
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def get_repo_status(repo_name: str) -> str:
        """Return index status for a repository.

        Includes indexed commit, current HEAD, staleness indicator,
        file count, symbol count, total tokens, and last indexed time.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)
            status = await ctx.context_store.get_repo_status(repo.id)

            current_head: str | None = None
            is_stale = False
            try:
                current_head = await ctx.git.get_head_commit(
                    Path(repo.local_path)
                )
                if status.indexed_commit:
                    is_stale = current_head != status.indexed_commit
            except Exception:
                pass

            parts: list[str] = [f"# Status: {repo.name}", ""]
            parts.append(
                f"- **Indexed commit:** {status.indexed_commit or 'Not indexed'}"
            )
            parts.append(f"- **Current HEAD:** {current_head or 'Unknown'}")
            stale_str = (
                "Yes"
                if is_stale
                else ("No" if status.indexed_commit else "N/A")
            )
            parts.append(f"- **Stale:** {stale_str}")
            parts.append(f"- **Files indexed:** {status.files_indexed}")
            parts.append(f"- **Symbols indexed:** {status.symbols_indexed}")
            parts.append(f"- **Total tokens:** {status.total_tokens:,}")
            parts.append(
                f"- **Last indexed:** {status.last_indexed_at or 'Never'}"
            )
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def sync_repo(repo_name: str) -> str:
        """Trigger an incremental sync for a repository.

        Processes only files changed since the last indexed commit.
        Returns a summary of changes made.
        """
        try:
            ctx = await _get_ctx()
            repo = await ctx.repo_manager.get_repo(repo_name)

            if repo.indexed_commit is None:
                raise NoIndexError(
                    f"Repository '{repo_name}' has no index. "
                    "Run 'codetex index' first."
                )

            result = await ctx.syncer.sync(repo)

            if result.already_current:
                return "Already up to date."

            parts: list[str] = ["# Sync Complete", ""]
            parts.append(f"- **Files added:** {result.files_added}")
            parts.append(f"- **Files modified:** {result.files_modified}")
            parts.append(f"- **Files deleted:** {result.files_deleted}")
            parts.append(
                f"- **Tier 1 rebuilt:** {'Yes' if result.tier1_rebuilt else 'No'}"
            )
            old = result.old_commit[:12] if result.old_commit else "-"
            new = result.new_commit[:12] if result.new_commit else "-"
            parts.append(f"- **Commits:** {old} → {new}")
            parts.append(f"- **Duration:** {result.duration_seconds:.1f}s")
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    @server.tool()
    async def list_repos() -> str:
        """List all registered repositories with their status.

        Returns a markdown table of repository names, remote URLs,
        indexed commits, and file counts.
        """
        try:
            ctx = await _get_ctx()
            repos = await ctx.repo_manager.list_repos()
            if not repos:
                return "No repositories registered."

            parts: list[str] = ["# Registered Repositories", ""]
            parts.append(
                "| Name | Remote URL | Indexed Commit | Last Indexed |"
            )
            parts.append(
                "|------|-----------|---------------|-------------|"
            )
            for repo in repos:
                commit = (
                    repo.indexed_commit[:12] if repo.indexed_commit else "-"
                )
                parts.append(
                    f"| {repo.name} "
                    f"| {repo.remote_url or '-'} "
                    f"| {commit} "
                    f"| {repo.last_indexed_at or '-'} |"
                )
            return "\n".join(parts)
        except CodetexError as exc:
            raise ValueError(str(exc)) from exc

    return server
