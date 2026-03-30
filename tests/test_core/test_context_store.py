from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.core.context_store import (
    ContextStore,
    FileContext,
    RepoStatus,
    SymbolDetail,
)
from codetex_mcp.storage.database import Database


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest_asyncio.fixture
async def db(db_path: Path) -> Database:  # type: ignore[misc]
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database  # type: ignore[misc]
    await database.close()


@pytest_asyncio.fixture
async def repo_id(db: Database) -> int:
    """Create a test repository and return its ID."""
    cursor = await db.execute(
        "INSERT INTO repositories (name, local_path, default_branch) VALUES (?, ?, ?)",
        ("test-repo", "/tmp/test-repo", "main"),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@pytest_asyncio.fixture
async def store(db: Database) -> ContextStore:
    return ContextStore(db)


# -- GetRepoOverview -------------------------------------------------------


class TestGetRepoOverview:
    @pytest.mark.asyncio
    async def test_returns_overview_when_exists(
        self, store: ContextStore, db: Database, repo_id: int
    ) -> None:
        await db.execute(
            "INSERT INTO repo_overviews (repo_id, overview, commit_sha) "
            "VALUES (?, ?, ?)",
            (repo_id, "# Test Repo Overview\nThis is a test.", "abc123"),
        )
        await db.conn.commit()

        result = await store.get_repo_overview(repo_id)
        assert result == "# Test Repo Overview\nThis is a test."

    @pytest.mark.asyncio
    async def test_returns_none_when_no_overview(
        self, store: ContextStore, repo_id: int
    ) -> None:
        result = await store.get_repo_overview(repo_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_repo(self, store: ContextStore) -> None:
        result = await store.get_repo_overview(9999)
        assert result is None


# -- GetFileContext ---------------------------------------------------------


class TestGetFileContext:
    @pytest_asyncio.fixture
    async def file_id(self, db: Database, repo_id: int) -> int:
        cursor = await db.execute(
            "INSERT INTO files (repo_id, path, language, lines_of_code, "
            "token_count, summary, role, imports_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                repo_id,
                "src/main.py",
                "python",
                100,
                500,
                "Main entry point",
                "entry",
                '["os", "sys"]',
            ),
        )
        await db.conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @pytest.mark.asyncio
    async def test_returns_file_context(
        self, store: ContextStore, db: Database, repo_id: int, file_id: int
    ) -> None:
        result = await store.get_file_context(repo_id, "src/main.py")
        assert result is not None
        assert isinstance(result, FileContext)
        assert result.summary == "Main entry point"
        assert result.role == "entry"
        assert result.imports == '["os", "sys"]'
        assert result.lines_of_code == 100
        assert result.token_count == 500
        assert result.symbols == []

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_file(
        self, store: ContextStore, repo_id: int
    ) -> None:
        result = await store.get_file_context(repo_id, "nonexistent.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_includes_symbols(
        self, store: ContextStore, db: Database, repo_id: int, file_id: int
    ) -> None:
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "main", "function", "def main():", 10, 20),
        )
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "Config", "class", "class Config:", 25, 50),
        )
        await db.conn.commit()

        result = await store.get_file_context(repo_id, "src/main.py")
        assert result is not None
        assert len(result.symbols) == 2
        assert result.symbols[0].name == "main"
        assert result.symbols[0].kind == "function"
        assert result.symbols[0].signature == "def main():"
        assert result.symbols[0].start_line == 10
        assert result.symbols[0].end_line == 20
        assert result.symbols[1].name == "Config"
        assert result.symbols[1].kind == "class"

    @pytest.mark.asyncio
    async def test_handles_null_fields(
        self, store: ContextStore, db: Database, repo_id: int
    ) -> None:
        await db.execute(
            "INSERT INTO files (repo_id, path, language, lines_of_code, token_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_id, "src/empty.py", "python", 0, 0),
        )
        await db.conn.commit()

        result = await store.get_file_context(repo_id, "src/empty.py")
        assert result is not None
        assert result.summary is None
        assert result.role is None
        assert result.imports is None


# -- GetSymbolDetail --------------------------------------------------------


class TestGetSymbolDetail:
    @pytest_asyncio.fixture
    async def file_id(self, db: Database, repo_id: int) -> int:
        cursor = await db.execute(
            "INSERT INTO files (repo_id, path, language, lines_of_code, token_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_id, "src/utils.py", "python", 50, 200),
        )
        await db.conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @pytest.mark.asyncio
    async def test_returns_symbol_detail(
        self, store: ContextStore, db: Database, repo_id: int, file_id: int
    ) -> None:
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "summary, start_line, end_line, parameters_json, return_type, calls_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_id,
                repo_id,
                "process_data",
                "function",
                "def process_data(items: list) -> int:",
                "Processes a list of items and returns the count.",
                10,
                30,
                '[{"name": "items", "type": "list"}]',
                "int",
                '["validate", "transform"]',
            ),
        )
        await db.conn.commit()

        result = await store.get_symbol_detail(repo_id, "process_data")
        assert result is not None
        assert isinstance(result, SymbolDetail)
        assert result.signature == "def process_data(items: list) -> int:"
        assert result.summary == "Processes a list of items and returns the count."
        assert result.parameters == '[{"name": "items", "type": "list"}]'
        assert result.return_type == "int"
        assert result.calls == '["validate", "transform"]'
        assert result.file_path == "src/utils.py"
        assert result.start_line == 10

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_symbol(
        self, store: ContextStore, repo_id: int
    ) -> None:
        result = await store.get_symbol_detail(repo_id, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_joins_file_path(
        self, store: ContextStore, db: Database, repo_id: int, file_id: int
    ) -> None:
        """Symbol detail includes the file path from the files table."""
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "helper", "function", "def helper():", 1, 5),
        )
        await db.conn.commit()

        result = await store.get_symbol_detail(repo_id, "helper")
        assert result is not None
        assert result.file_path == "src/utils.py"


# -- GetRepoStatus ----------------------------------------------------------


class TestGetRepoStatus:
    @pytest.mark.asyncio
    async def test_empty_repo_status(self, store: ContextStore, repo_id: int) -> None:
        result = await store.get_repo_status(repo_id)
        assert isinstance(result, RepoStatus)
        assert result.indexed_commit is None
        assert result.files_indexed == 0
        assert result.symbols_indexed == 0
        assert result.total_tokens == 0
        assert result.last_indexed_at is None

    @pytest.mark.asyncio
    async def test_status_with_data(
        self, store: ContextStore, db: Database, repo_id: int
    ) -> None:
        # Update repo with indexed commit
        await db.execute(
            "UPDATE repositories SET indexed_commit = ?, last_indexed_at = datetime('now') "
            "WHERE id = ?",
            ("abc123def", repo_id),
        )

        # Add files
        cursor = await db.execute(
            "INSERT INTO files (repo_id, path, language, lines_of_code, token_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_id, "src/a.py", "python", 50, 200),
        )
        file_id = cursor.lastrowid
        await db.execute(
            "INSERT INTO files (repo_id, path, language, lines_of_code, token_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_id, "src/b.py", "python", 30, 100),
        )

        # Add symbols
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "foo", "function", "def foo():", 1, 10),
        )
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "bar", "function", "def bar():", 12, 20),
        )
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
            "start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, repo_id, "Baz", "class", "class Baz:", 22, 40),
        )
        await db.conn.commit()

        result = await store.get_repo_status(repo_id)
        assert result.indexed_commit == "abc123def"
        assert result.files_indexed == 2
        assert result.symbols_indexed == 3
        assert result.total_tokens == 300
        assert result.last_indexed_at is not None

    @pytest.mark.asyncio
    async def test_status_nonexistent_repo(self, store: ContextStore) -> None:
        """Status for a repo ID not in the DB returns zeros/None."""
        result = await store.get_repo_status(9999)
        assert result.indexed_commit is None
        assert result.files_indexed == 0
        assert result.symbols_indexed == 0
        assert result.total_tokens == 0
        assert result.last_indexed_at is None
