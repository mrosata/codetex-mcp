"""Tests for CLI commands — add, list, status, config, index, sync, context, serve."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from codetex_mcp.cli.app import app
from codetex_mcp.config.settings import Settings
from codetex_mcp.core import AppContext
from codetex_mcp.core.context_store import (
    ContextStore,
    FileContext,
    RepoStatus,
    SymbolBrief,
    SymbolDetail,
)
from codetex_mcp.core.indexer import IndexResult
from codetex_mcp.core.repo_manager import RepoManager
from codetex_mcp.core.search_engine import SearchResult
from codetex_mcp.core.syncer import SyncResult
from codetex_mcp.exceptions import (
    CodetexError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import Repository

runner = CliRunner()


def _make_repo(
    *,
    name: str = "my-repo",
    remote_url: str | None = "https://github.com/user/my-repo.git",
    local_path: str = "/tmp/repos/my-repo",
    indexed_commit: str | None = None,
    last_indexed_at: str | None = None,
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
    ctx = AppContext(
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
    return ctx


# ---- add command ----


class TestAddCommand:
    def test_add_local(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.add_local.return_value = _make_repo(
            local_path="/home/user/my-repo"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["add", "/home/user/my-repo"])

        assert result.exit_code == 0
        assert "my-repo" in result.output
        mock_ctx.repo_manager.add_local.assert_called_once()

    def test_add_remote(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.add_remote.return_value = _make_repo()

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["add", "https://github.com/user/my-repo.git"]
            )

        assert result.exit_code == 0
        assert "my-repo" in result.output
        mock_ctx.repo_manager.add_remote.assert_called_once()

    def test_add_duplicate_error(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.add_local.side_effect = RepositoryAlreadyExistsError(
            "Repository 'my-repo' already exists"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["add", "/home/user/my-repo"])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_add_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.add_local.return_value = _make_repo()

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["add", "/home/user/my-repo"])

        mock_ctx.db.close.assert_called_once()


# ---- list command ----


class TestListCommand:
    def test_list_repos(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.list_repos.return_value = [
            _make_repo(
                name="repo-a",
                indexed_commit="abc123def456",
                last_indexed_at="2026-01-15T10:30:00",
            ),
            _make_repo(name="repo-b", remote_url=None),
        ]

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "repo-a" in result.output
        assert "repo-b" in result.output
        assert "abc123def456"[:12] in result.output

    def test_list_empty(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.list_repos.return_value = []

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No repositories registered" in result.output

    def test_list_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.list_repos.return_value = []

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["list"])

        mock_ctx.db.close.assert_called_once()


# ---- status command ----


class TestStatusCommand:
    def test_status_indexed(self) -> None:
        mock_ctx = _make_mock_ctx()
        repo = _make_repo(
            indexed_commit="abc123def456789",
            last_indexed_at="2026-01-15T10:30:00",
        )
        mock_ctx.repo_manager.get_repo.return_value = repo
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit="abc123def456789",
            files_indexed=42,
            symbols_indexed=150,
            total_tokens=50000,
            last_indexed_at="2026-01-15T10:30:00",
        )
        mock_ctx.git.get_head_commit.return_value = "abc123def456789"

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["status", "my-repo"])

        assert result.exit_code == 0
        assert "my-repo" in result.output
        assert "42" in result.output
        assert "150" in result.output
        assert "50,000" in result.output
        assert "No" in result.output  # Not stale

    def test_status_stale(self) -> None:
        mock_ctx = _make_mock_ctx()
        repo = _make_repo(indexed_commit="old_commit_sha")
        mock_ctx.repo_manager.get_repo.return_value = repo
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit="old_commit_sha",
            files_indexed=10,
            symbols_indexed=20,
            total_tokens=5000,
            last_indexed_at="2026-01-10T00:00:00",
        )
        mock_ctx.git.get_head_commit.return_value = "new_commit_sha"

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["status", "my-repo"])

        assert result.exit_code == 0
        assert "Yes" in result.output  # Stale

    def test_status_not_indexed(self) -> None:
        mock_ctx = _make_mock_ctx()
        repo = _make_repo()
        mock_ctx.repo_manager.get_repo.return_value = repo
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit=None,
            files_indexed=0,
            symbols_indexed=0,
            total_tokens=0,
            last_indexed_at=None,
        )
        mock_ctx.git.get_head_commit.return_value = "some_head"

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["status", "my-repo"])

        assert result.exit_code == 0
        assert "Not indexed" in result.output
        assert "N/A" in result.output  # Stale shows N/A

    def test_status_repo_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "Repository 'no-such' not found"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["status", "no-such"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_status_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        repo = _make_repo()
        mock_ctx.repo_manager.get_repo.return_value = repo
        mock_ctx.context_store.get_repo_status.return_value = RepoStatus(
            indexed_commit=None,
            files_indexed=0,
            symbols_indexed=0,
            total_tokens=0,
            last_indexed_at=None,
        )
        mock_ctx.git.get_head_commit.return_value = "head"

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["status", "my-repo"])

        mock_ctx.db.close.assert_called_once()


# ---- config show command ----


class TestConfigShowCommand:
    def test_config_show(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
            llm_model="claude-sonnet-4-5-20250929",
            llm_api_key="sk-ant-test",
            max_file_size_kb=512,
            max_concurrent_llm_calls=5,
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "claude-sonnet-4-5-20250929" in result.output
        assert "***" in result.output  # API key masked
        assert "512" in result.output

    def test_config_show_no_api_key(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
            llm_api_key=None,
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "Not set" in result.output


# ---- config set command ----


class TestConfigSetCommand:
    def test_set_string_value(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(app, ["config", "set", "llm.model", "claude-opus-4-6"])

        assert result.exit_code == 0
        assert "llm.model" in result.output

        # Verify the TOML file was written
        config_path = tmp_path / "config.toml"
        assert config_path.exists()
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["llm"]["model"] == "claude-opus-4-6"

    def test_set_int_value(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(
                app, ["config", "set", "indexing.max_file_size_kb", "1024"]
            )

        assert result.exit_code == 0
        config_path = tmp_path / "config.toml"
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["indexing"]["max_file_size_kb"] == 1024

    def test_set_float_value(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(
                app, ["config", "set", "indexing.tier1_rebuild_threshold", "0.25"]
            )

        assert result.exit_code == 0
        config_path = tmp_path / "config.toml"
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["indexing"]["tier1_rebuild_threshold"] == 0.25

    def test_set_unknown_key(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(app, ["config", "set", "bad.key", "value"])

        assert result.exit_code == 1
        assert "Unknown config key" in result.output

    def test_set_invalid_int(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(
                app, ["config", "set", "indexing.max_file_size_kb", "not-a-number"]
            )

        assert result.exit_code == 1
        assert "integer" in result.output

    def test_set_preserves_existing(self, tmp_path: Path) -> None:
        """Setting one key doesn't erase other existing config values."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('[llm]\nmodel = "old-model"\napi_key = "sk-test"\n')

        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(
                app, ["config", "set", "llm.model", "new-model"]
            )

        assert result.exit_code == 0
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["llm"]["model"] == "new-model"
        assert data["llm"]["api_key"] == "sk-test"  # Preserved

    def test_set_api_key(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            repos_dir=tmp_path / "repos",
            db_path=tmp_path / "test.db",
        )

        with patch("codetex_mcp.cli.app.Settings.load", return_value=settings):
            result = runner.invoke(
                app, ["config", "set", "llm.api_key", "sk-ant-new-key"]
            )

        assert result.exit_code == 0
        config_path = tmp_path / "config.toml"
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["llm"]["api_key"] == "sk-ant-new-key"


# ---- error handling ----


class TestErrorHandling:
    def test_codetex_error_caught(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.list_repos.side_effect = CodetexError("Something broke")

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 1
        assert "Something broke" in result.output

    def test_codetex_error_subclass_caught(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "Repository 'x' not found"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["status", "x"])

        assert result.exit_code == 1
        assert "not found" in result.output


# ---- main function ----


# ---- index command ----


class TestIndexCommand:
    def test_index_full(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.indexer.index.return_value = IndexResult(
            files_indexed=25,
            symbols_extracted=100,
            llm_calls_made=30,
            tokens_used=15000,
            duration_seconds=12.5,
            commit_sha="abc123def456789",
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["index", "my-repo"])

        assert result.exit_code == 0
        assert "25" in result.output
        assert "100" in result.output
        assert "15,000" in result.output
        assert "12.5" in result.output
        assert "abc123def456" in result.output
        mock_ctx.indexer.index.assert_called_once()
        call_kwargs = mock_ctx.indexer.index.call_args
        assert call_kwargs[1].get("dry_run") is not True or call_kwargs[0] == ()

    def test_index_dry_run(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.indexer.index.return_value = IndexResult(
            files_indexed=25,
            symbols_extracted=100,
            llm_calls_made=30,
            tokens_used=15000,
            duration_seconds=0.0,
            commit_sha="",
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["index", "my-repo", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry Run" in result.output
        assert "25" in result.output
        assert "15,000" in result.output
        # Verify dry_run=True was passed
        mock_ctx.indexer.index.assert_called_once()
        _, kwargs = mock_ctx.indexer.index.call_args
        assert kwargs.get("dry_run") is True

    def test_index_with_path_filter(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.indexer.index.return_value = IndexResult(
            files_indexed=5,
            symbols_extracted=10,
            llm_calls_made=6,
            tokens_used=3000,
            duration_seconds=2.0,
            commit_sha="abc123",
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["index", "my-repo", "--path", "src/"])

        assert result.exit_code == 0
        _, kwargs = mock_ctx.indexer.index.call_args
        assert kwargs.get("path_filter") == "src/"

    def test_index_repo_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "Repository 'no-such' not found"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["index", "no-such"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_index_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.indexer.index.return_value = IndexResult(
            files_indexed=0,
            symbols_extracted=0,
            llm_calls_made=0,
            tokens_used=0,
            duration_seconds=0.0,
            commit_sha="abc",
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["index", "my-repo"])

        mock_ctx.db.close.assert_called_once()


# ---- sync command ----


class TestSyncCommand:
    def test_sync_changes(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=False,
            files_added=3,
            files_modified=2,
            files_deleted=1,
            llm_calls_made=8,
            tokens_used=5000,
            tier1_rebuilt=True,
            old_commit="aaa111bbb222",
            new_commit="ccc333ddd444",
            duration_seconds=5.2,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["sync", "my-repo"])

        assert result.exit_code == 0
        assert "3" in result.output  # files added
        assert "2" in result.output  # files modified
        assert "1" in result.output  # files deleted
        assert "5,000" in result.output
        assert "5.2" in result.output
        assert "Yes" in result.output  # tier1 rebuilt

    def test_sync_already_current(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=True,
            files_added=0,
            files_modified=0,
            files_deleted=0,
            llm_calls_made=0,
            tokens_used=0,
            tier1_rebuilt=False,
            old_commit="abc123",
            new_commit="abc123",
            duration_seconds=0.1,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["sync", "my-repo"])

        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_sync_dry_run(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=False,
            files_added=2,
            files_modified=1,
            files_deleted=0,
            llm_calls_made=4,
            tokens_used=2000,
            tier1_rebuilt=False,
            old_commit="aaa111",
            new_commit="bbb222",
            duration_seconds=0.0,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["sync", "my-repo", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry Run" in result.output
        _, kwargs = mock_ctx.syncer.sync.call_args
        assert kwargs.get("dry_run") is True

    def test_sync_with_path_filter(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=False,
            files_added=1,
            files_modified=0,
            files_deleted=0,
            llm_calls_made=1,
            tokens_used=500,
            tier1_rebuilt=False,
            old_commit="aaa",
            new_commit="bbb",
            duration_seconds=1.0,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["sync", "my-repo", "--path", "src/"])

        assert result.exit_code == 0
        _, kwargs = mock_ctx.syncer.sync.call_args
        assert kwargs.get("path_filter") == "src/"

    def test_sync_repo_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "Repository 'no-such' not found"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["sync", "no-such"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_sync_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.syncer.sync.return_value = SyncResult(
            already_current=True,
            files_added=0,
            files_modified=0,
            files_deleted=0,
            llm_calls_made=0,
            tokens_used=0,
            tier1_rebuilt=False,
            old_commit="",
            new_commit="",
            duration_seconds=0.0,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["sync", "my-repo"])

        mock_ctx.db.close.assert_called_once()


# ---- context command ----


class TestContextCommand:
    def test_context_overview(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_overview.return_value = (
            "# my-repo\n\nA sample repository for testing."
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["context", "my-repo"])

        assert result.exit_code == 0
        assert "sample repository" in result.output

    def test_context_overview_not_indexed(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_overview.return_value = None

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["context", "my-repo"])

        assert result.exit_code == 0
        assert "No index found" in result.output

    def test_context_file(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_file_context.return_value = FileContext(
            summary="Handles database connections.",
            role="data access",
            imports='["sqlite3"]',
            symbols=[
                SymbolBrief(
                    name="connect",
                    kind="function",
                    signature="def connect(path: str)",
                    start_line=10,
                    end_line=25,
                ),
            ],
            lines_of_code=50,
            token_count=300,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["context", "my-repo", "--file", "db.py"])

        assert result.exit_code == 0
        assert "database connections" in result.output
        assert "data access" in result.output
        assert "connect" in result.output

    def test_context_file_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_file_context.return_value = None

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["context", "my-repo", "--file", "nonexistent.py"]
            )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_context_symbol(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_symbol_detail.return_value = SymbolDetail(
            signature="def connect(path: str) -> Connection",
            summary="Establishes a database connection.",
            parameters='[{"name": "path", "type": "str"}]',
            return_type="Connection",
            calls='["sqlite3.connect"]',
            file_path="db.py",
            start_line=10,
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["context", "my-repo", "--symbol", "connect"]
            )

        assert result.exit_code == 0
        assert "connect" in result.output
        assert "db.py" in result.output
        assert "Connection" in result.output

    def test_context_symbol_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_symbol_detail.return_value = None

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["context", "my-repo", "--symbol", "nonexistent"]
            )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_context_search(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.search_engine.search.return_value = [
            SearchResult(
                kind="file",
                path="db.py",
                name="db.py",
                summary="Database connection module.",
                score=0.1234,
            ),
            SearchResult(
                kind="symbol",
                path="db.py",
                name="connect",
                summary="Connect to database.",
                score=0.2345,
            ),
        ]

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["context", "my-repo", "--query", "database connection"]
            )

        assert result.exit_code == 0
        assert "db.py" in result.output
        assert "connect" in result.output
        assert "0.1234" in result.output

    def test_context_search_empty(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.search_engine.search.return_value = []

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(
                app, ["context", "my-repo", "--query", "something obscure"]
            )

        assert result.exit_code == 0
        assert "No results" in result.output

    def test_context_repo_not_found(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.side_effect = RepositoryNotFoundError(
            "Repository 'no-such' not found"
        )

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            result = runner.invoke(app, ["context", "no-such"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_context_closes_db(self) -> None:
        mock_ctx = _make_mock_ctx()
        mock_ctx.repo_manager.get_repo.return_value = _make_repo()
        mock_ctx.context_store.get_repo_overview.return_value = "overview"

        with patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx):
            runner.invoke(app, ["context", "my-repo"])

        mock_ctx.db.close.assert_called_once()


# ---- serve command ----


class TestServeCommand:
    def test_serve_creates_and_runs_server(self) -> None:
        mock_server = MagicMock()
        with patch(
            "codetex_mcp.server.mcp_server.create_server", return_value=mock_server
        ) as mock_create:
            result = runner.invoke(app, ["serve"])

        mock_create.assert_called_once()
        mock_server.run.assert_called_once()


# ---- main function ----


class TestMainFunction:
    def test_main_exists(self) -> None:
        from codetex_mcp.cli.app import main

        assert callable(main)
