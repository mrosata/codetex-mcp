from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.analysis.parser import Parser
from codetex_mcp.config.settings import Settings
from codetex_mcp.core import AppContext, create_app
from codetex_mcp.core.context_store import ContextStore
from codetex_mcp.core.indexer import Indexer
from codetex_mcp.core.repo_manager import RepoManager
from codetex_mcp.core.search_engine import SearchEngine
from codetex_mcp.core.syncer import Syncer
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.llm.provider import LLMProvider
from codetex_mcp.storage.database import Database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        repos_dir=tmp_path / "data" / "repos",
        db_path=tmp_path / "test.db",
    )


class TestAppContext:
    def test_fields(self, settings: Settings, tmp_path: Path) -> None:
        """AppContext has all expected fields."""
        db = Database(tmp_path / "test.db")
        git = GitOperations(settings)
        ctx = AppContext(
            settings=settings,
            db=db,
            git=git,
            parser=None,  # type: ignore[arg-type]
            llm=None,  # type: ignore[arg-type]
            embedder=None,  # type: ignore[arg-type]
            repo_manager=None,  # type: ignore[arg-type]
            indexer=None,  # type: ignore[arg-type]
            syncer=None,  # type: ignore[arg-type]
            context_store=None,  # type: ignore[arg-type]
            search_engine=None,  # type: ignore[arg-type]
        )
        assert ctx.settings is settings
        assert ctx.db is db
        assert ctx.git is git


class TestCreateApp:
    @pytest.mark.asyncio
    async def test_returns_app_context(self, settings: Settings) -> None:
        """create_app returns an AppContext instance."""
        ctx = await create_app(settings)
        try:
            assert isinstance(ctx, AppContext)
        finally:
            await ctx.db.close()

    @pytest.mark.asyncio
    async def test_all_fields_populated(self, settings: Settings) -> None:
        """All AppContext fields are populated with correct types."""
        ctx = await create_app(settings)
        try:
            assert isinstance(ctx.settings, Settings)
            assert isinstance(ctx.db, Database)
            assert isinstance(ctx.git, GitOperations)
            assert isinstance(ctx.parser, Parser)
            assert isinstance(ctx.llm, LLMProvider)
            assert isinstance(ctx.embedder, Embedder)
            assert isinstance(ctx.repo_manager, RepoManager)
            assert isinstance(ctx.indexer, Indexer)
            assert isinstance(ctx.syncer, Syncer)
            assert isinstance(ctx.context_store, ContextStore)
            assert isinstance(ctx.search_engine, SearchEngine)
        finally:
            await ctx.db.close()

    @pytest.mark.asyncio
    async def test_database_is_migrated(self, settings: Settings) -> None:
        """Database is connected and migrated after create_app."""
        ctx = await create_app(settings)
        try:
            # Verify tables exist by querying schema_version
            result = await ctx.db.execute(
                "SELECT MAX(version) FROM schema_version"
            )
            row = await result.fetchone()
            assert row is not None
            assert row[0] >= 1
        finally:
            await ctx.db.close()

    @pytest.mark.asyncio
    async def test_uses_provided_settings(self, settings: Settings) -> None:
        """create_app uses the provided Settings object."""
        ctx = await create_app(settings)
        try:
            assert ctx.settings is settings
            assert ctx.db.db_path == settings.db_path
        finally:
            await ctx.db.close()

    @pytest.mark.asyncio
    async def test_default_settings_when_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_app loads default Settings when None is passed."""
        # Point data dir to tmp_path to avoid polluting user home
        monkeypatch.setenv("CODETEX_DATA_DIR", str(tmp_path / "default_data"))
        ctx = await create_app(None)
        try:
            assert ctx.settings.data_dir == tmp_path / "default_data"
        finally:
            await ctx.db.close()

    @pytest.mark.asyncio
    async def test_tables_exist_after_create(self, settings: Settings) -> None:
        """Core tables exist after create_app migration."""
        ctx = await create_app(settings)
        try:
            # Check that key tables exist
            for table in ("repositories", "files", "symbols", "dependencies", "repo_overviews"):
                result = await ctx.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                row = await result.fetchone()
                assert row is not None, f"Table {table} should exist"
        finally:
            await ctx.db.close()
