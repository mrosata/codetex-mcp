"""Tests for MCP server tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from codetex_mcp.config.settings import Settings
from codetex_mcp.core import AppContext
from codetex_mcp.core.context_store import (
    ContextStore,
    FileContext,
    RepoStatus,
    SymbolBrief,
    SymbolDetail,
)
from codetex_mcp.core.repo_manager import RepoManager
from codetex_mcp.core.search_engine import SearchResult
from codetex_mcp.core.syncer import SyncResult
from mcp.server.fastmcp.exceptions import ToolError

from codetex_mcp.exceptions import RepositoryNotFoundError
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import Repository

import codetex_mcp.server.mcp_server as server_mod


def _make_repo(
    *,
    name: str = "my-repo",
    remote_url: str | None = "https://github.com/user/my-repo.git",
    local_path: str = "/tmp/repos/my-repo",
    indexed_commit: str | None = "abc123def456",
    last_indexed_at: str | None = "2026-01-15T10:30:00",
) -> Repository:
    return Repository(
        id=1,
        name=name,
        remote_url=remote_url,
        local_path=local_path,
        default_branch="main",
        indexed_commit=indexed_commit,
        last_indexed_at=last_indexed_at,
        created_at="2026-01-01T00:00:00",
    )


def _make_mock_ctx() -> AppContext:
    """Create a mock AppContext with all services mocked."""
    return AppContext(
        settings=Settings(
            data_dir=Path("/tmp/test-data"),
            repos_dir=Path("/tmp/test-data/repos"),
            db_path=Path("/tmp/test-data/test.db"),
        ),
        db=AsyncMock(spec=Database),
        git=AsyncMock(spec=GitOperations),
        parser=AsyncMock(),
        llm=AsyncMock(),
        embedder=AsyncMock(),
        repo_manager=AsyncMock(spec=RepoManager),
        indexer=AsyncMock(),
        syncer=AsyncMock(),
        context_store=AsyncMock(spec=ContextStore),
        search_engine=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _reset_app_ctx() -> None:
    """Reset the module-level _app_ctx before each test."""
    server_mod._app_ctx = None


@pytest.fixture()
def mock_ctx() -> AppContext:
    return _make_mock_ctx()


# ---- create_server ----


class TestCreateServer:
    def test_returns_fastmcp_instance(self) -> None:
        server = server_mod.create_server()
        assert server.name == "codetex"

    def test_tools_registered(self) -> None:
        server = server_mod.create_server()
        tool_names = {t.name for t in server._tool_manager.list_tools()}
        assert tool_names == {
            "get_repo_overview",
            "get_file_context",
            "get_symbol_detail",
            "search_context",
            "get_repo_status",
            "sync_repo",
            "list_repos",
        }


# ---- get_repo_overview ----


class TestGetRepoOverview:
    @pytest.mark.asyncio
    async def test_returns_overview(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_overview.return_value = (
            "# My Repo\n\nOverview text."
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_repo_overview"].run({"repo_name": "my-repo"})

        assert "My Repo" in result

    @pytest.mark.asyncio
    async def test_no_index_raises(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_overview.return_value = None

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            with pytest.raises(ToolError, match="no index"):
                await tools["get_repo_overview"].run({"repo_name": "my-repo"})

    @pytest.mark.asyncio
    async def test_repo_not_found_raises(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "not found"
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            with pytest.raises(ToolError, match="not found"):
                await tools["get_repo_overview"].run({"repo_name": "nope"})


# ---- get_file_context ----


class TestGetFileContext:
    @pytest.mark.asyncio
    async def test_returns_file_context(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_file_context.return_value = FileContext(
            summary="Handles authentication logic.",
            role="service",
            imports='[{"module": "os", "names": []}]',
            symbols=[
                SymbolBrief(
                    name="login",
                    kind="function",
                    signature="def login(user, pwd)",
                    start_line=10,
                    end_line=25,
                )
            ],
            lines_of_code=100,
            token_count=500,
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_file_context"].run(
                {"repo_name": "my-repo", "file_path": "src/auth.py"}
            )

        assert "src/auth.py" in result
        assert "Handles authentication" in result
        assert "service" in result
        assert "100" in result
        assert "500" in result
        assert "login" in result

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_file_context.return_value = None

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            with pytest.raises(ToolError, match="not found in index"):
                await tools["get_file_context"].run(
                    {"repo_name": "my-repo", "file_path": "missing.py"}
                )


# ---- get_symbol_detail ----


class TestGetSymbolDetail:
    @pytest.mark.asyncio
    async def test_returns_symbol_detail(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_symbol_detail.return_value = SymbolDetail(
            signature="def process(data: list) -> dict",
            summary="Processes input data and returns results.",
            parameters='[{"name": "data", "type": "list"}]',
            return_type="dict",
            calls='["validate", "transform"]',
            file_path="src/core.py",
            start_line=42,
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_symbol_detail"].run(
                {"repo_name": "my-repo", "symbol_name": "process"}
            )

        assert "def process(data: list) -> dict" in result
        assert "src/core.py:42" in result
        assert "Processes input data" in result
        assert "Parameters" in result
        assert "Returns" in result
        assert "Calls" in result

    @pytest.mark.asyncio
    async def test_symbol_not_found_raises(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_symbol_detail.return_value = None

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            with pytest.raises(ToolError, match="not found in index"):
                await tools["get_symbol_detail"].run(
                    {"repo_name": "my-repo", "symbol_name": "nope"}
                )


# ---- search_context ----


class TestSearchContext:
    @pytest.mark.asyncio
    async def test_returns_results(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.search_engine.search.return_value = [
            SearchResult(
                kind="file",
                path="src/auth.py",
                name="src/auth.py",
                summary="Authentication module",
                score=0.1234,
            ),
            SearchResult(
                kind="symbol",
                path="src/auth.py",
                name="login",
                summary="Login handler function",
                score=0.2345,
            ),
        ]

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["search_context"].run(
                {"repo_name": "my-repo", "query": "authentication"}
            )

        assert "Search Results" in result
        assert "0.1234" in result
        assert "src/auth.py" in result
        assert "login" in result

    @pytest.mark.asyncio
    async def test_no_results(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.search_engine.search.return_value = []

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["search_context"].run(
                {"repo_name": "my-repo", "query": "nothing"}
            )

        assert "No results found" in result

    @pytest.mark.asyncio
    async def test_max_results_passed(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.search_engine.search.return_value = []

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            await tools["search_context"].run(
                {"repo_name": "my-repo", "query": "test", "max_results": 5}
            )

        mock_ctx.search_engine.search.assert_called_once_with(1, "test", max_results=5)


# ---- get_repo_status ----


class TestGetRepoStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit="abc123def456",
            files_indexed=42,
            symbols_indexed=200,
            total_tokens=15000,
            last_indexed_at="2026-01-15T10:30:00",
        )
        mock_ctx.git.get_head_commit.return_value = "abc123def456"

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_repo_status"].run({"repo_name": "my-repo"})

        assert "my-repo" in result
        assert "abc123def456" in result
        assert "42" in result
        assert "200" in result
        assert "15,000" in result
        assert "No" in result  # not stale

    @pytest.mark.asyncio
    async def test_stale_repo(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit="abc123def456",
            files_indexed=10,
            symbols_indexed=50,
            total_tokens=5000,
            last_indexed_at="2026-01-10T10:00:00",
        )
        mock_ctx.git.get_head_commit.return_value = "different_head_sha"

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_repo_status"].run({"repo_name": "my-repo"})

        assert "Yes" in result  # stale

    @pytest.mark.asyncio
    async def test_not_indexed(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo(indexed_commit=None)
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit=None,
            files_indexed=0,
            symbols_indexed=0,
            total_tokens=0,
            last_indexed_at=None,
        )
        mock_ctx.git.get_head_commit.return_value = "somehead"

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["get_repo_status"].run({"repo_name": "my-repo"})

        assert "Not indexed" in result
        assert "N/A" in result


# ---- sync_repo ----


class TestSyncRepo:
    @pytest.mark.asyncio
    async def test_sync_with_changes(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=False,
            files_added=3,
            files_modified=2,
            files_deleted=1,
            llm_calls_made=10,
            tokens_used=5000,
            tier1_rebuilt=True,
            old_commit="abc123def456",
            new_commit="def456abc789",
            duration_seconds=12.5,
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["sync_repo"].run({"repo_name": "my-repo"})

        assert "Sync Complete" in result
        assert "3" in result
        assert "2" in result
        assert "1" in result
        assert "Yes" in result  # tier1 rebuilt
        assert "abc123def456" in result  # old commit shown (truncated to 12 chars)
        assert "def456abc789" in result  # new commit shown (truncated to 12 chars)

    @pytest.mark.asyncio
    async def test_already_current(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=True,
            files_added=0,
            files_modified=0,
            files_deleted=0,
            llm_calls_made=0,
            tokens_used=0,
            tier1_rebuilt=False,
            old_commit="abc123def456",
            new_commit="abc123def456",
            duration_seconds=0.1,
        )

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["sync_repo"].run({"repo_name": "my-repo"})

        assert "Already up to date" in result

    @pytest.mark.asyncio
    async def test_no_index_raises(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.get_repo.return_value = _make_repo(indexed_commit=None)

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            with pytest.raises(ToolError, match="no index"):
                await tools["sync_repo"].run({"repo_name": "my-repo"})


# ---- list_repos ----


class TestListRepos:
    @pytest.mark.asyncio
    async def test_returns_repos(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.list_repos.return_value = [
            _make_repo(name="repo-a"),
            _make_repo(name="repo-b", indexed_commit=None, last_indexed_at=None),
        ]

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["list_repos"].run({})

        assert "Registered Repositories" in result
        assert "repo-a" in result
        assert "repo-b" in result
        assert "abc123def456" in result  # truncated commit for repo-a

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_ctx: AppContext) -> None:
        mock_ctx.repo_manager.list_repos.return_value = []

        server = server_mod.create_server()
        with patch.object(server_mod, "_app_ctx", mock_ctx):
            tools = {t.name: t for t in server._tool_manager.list_tools()}
            result = await tools["list_repos"].run({})

        assert "No repositories registered" in result


# ---- _get_ctx ----


class TestGetCtx:
    @pytest.mark.asyncio
    async def test_creates_app_on_first_call(self) -> None:
        mock_ctx = _make_mock_ctx()
        with patch(
            "codetex_mcp.server.mcp_server.create_app", return_value=mock_ctx
        ) as mock_create:
            result = await server_mod._get_ctx()

        assert result is mock_ctx
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuses_app_on_second_call(self) -> None:
        mock_ctx = _make_mock_ctx()
        with patch(
            "codetex_mcp.server.mcp_server.create_app", return_value=mock_ctx
        ) as mock_create:
            first = await server_mod._get_ctx()
            second = await server_mod._get_ctx()

        assert first is second
        mock_create.assert_called_once()
