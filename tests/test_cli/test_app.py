"""Tests for CLI commands — add, list, status, config."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from codetex_mcp.cli.app import app
from codetex_mcp.config.settings import Settings
from codetex_mcp.core import AppContext
from codetex_mcp.core.context_store import ContextStore, RepoStatus
from codetex_mcp.core.repo_manager import RepoManager
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


class TestMainFunction:
    def test_main_exists(self) -> None:
        from codetex_mcp.cli.app import main

        assert callable(main)
