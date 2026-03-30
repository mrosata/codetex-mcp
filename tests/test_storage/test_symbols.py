from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.storage.database import Database
from codetex_mcp.storage.files import upsert_file
from codetex_mcp.storage.repositories import create_repo
from codetex_mcp.storage.symbols import (
    SymbolRecord,
    delete_symbols_by_file,
    get_symbol,
    list_symbols_by_file,
    update_symbol_summary,
    upsert_symbol,
)


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
async def repo_id(db: Database) -> int:  # type: ignore[misc]
    repo = await create_repo(db, "test-repo", None, "/tmp/test-repo", "main")
    return repo.id


@pytest_asyncio.fixture
async def file_id(db: Database, repo_id: int) -> int:  # type: ignore[misc]
    return await upsert_file(db, repo_id, "src/main.py", "python", 100, 500, None)


class TestUpsertSymbol:
    @pytest.mark.asyncio
    async def test_upsert_returns_symbol_id(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        symbol_id = await upsert_symbol(
            db,
            file_id,
            repo_id,
            "my_func",
            "function",
            "def my_func(x: int) -> str",
            None,
            10,
            20,
            None,
            "str",
            None,
        )
        assert symbol_id > 0

    @pytest.mark.asyncio
    async def test_upsert_stores_all_fields(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        params = json.dumps(
            [{"name": "x", "type_annotation": "int", "default_value": None}]
        )
        calls = json.dumps(["print", "str"])
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "process",
            "function",
            "def process(x: int) -> str",
            "Process the input.",
            5,
            15,
            params,
            "str",
            calls,
        )
        record = await get_symbol(db, repo_id, "process")
        assert record is not None
        assert isinstance(record, SymbolRecord)
        assert record.file_id == file_id
        assert record.repo_id == repo_id
        assert record.name == "process"
        assert record.kind == "function"
        assert record.signature == "def process(x: int) -> str"
        assert record.docstring == "Process the input."
        assert record.summary is None
        assert record.start_line == 5
        assert record.end_line == 15
        assert record.parameters_json == params
        assert record.return_type == "str"
        assert record.calls_json == calls
        assert record.updated_at is not None


class TestUpdateSymbolSummary:
    @pytest.mark.asyncio
    async def test_update_sets_summary(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        symbol_id = await upsert_symbol(
            db,
            file_id,
            repo_id,
            "compute",
            "function",
            "def compute()",
            None,
            1,
            10,
            None,
            None,
            None,
        )
        await update_symbol_summary(db, symbol_id, "Computes the result")
        record = await get_symbol(db, repo_id, "compute")
        assert record is not None
        assert record.summary == "Computes the result"


class TestGetSymbol:
    @pytest.mark.asyncio
    async def test_get_existing_symbol(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "find_me",
            "function",
            "def find_me()",
            None,
            1,
            5,
            None,
            None,
            None,
        )
        record = await get_symbol(db, repo_id, "find_me")
        assert record is not None
        assert record.name == "find_me"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(
        self, db: Database, repo_id: int
    ) -> None:
        result = await get_symbol(db, repo_id, "no_such_symbol")
        assert result is None


class TestListSymbolsByFile:
    @pytest.mark.asyncio
    async def test_list_empty(self, db: Database, file_id: int) -> None:
        symbols = await list_symbols_by_file(db, file_id)
        assert symbols == []

    @pytest.mark.asyncio
    async def test_list_ordered_by_start_line(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "second_func",
            "function",
            "def second_func()",
            None,
            20,
            30,
            None,
            None,
            None,
        )
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "first_func",
            "function",
            "def first_func()",
            None,
            1,
            10,
            None,
            None,
            None,
        )
        symbols = await list_symbols_by_file(db, file_id)
        assert len(symbols) == 2
        assert symbols[0].name == "first_func"
        assert symbols[1].name == "second_func"


class TestDeleteSymbolsByFile:
    @pytest.mark.asyncio
    async def test_delete_removes_all_symbols_for_file(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "func_a",
            "function",
            "def func_a()",
            None,
            1,
            5,
            None,
            None,
            None,
        )
        await upsert_symbol(
            db,
            file_id,
            repo_id,
            "func_b",
            "function",
            "def func_b()",
            None,
            10,
            15,
            None,
            None,
            None,
        )
        await delete_symbols_by_file(db, file_id)
        symbols = await list_symbols_by_file(db, file_id)
        assert symbols == []

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file_does_not_raise(self, db: Database) -> None:
        await delete_symbols_by_file(db, 9999)


class TestCascadeBehavior:
    @pytest.mark.asyncio
    async def test_file_delete_cascades_symbols(
        self, db: Database, repo_id: int
    ) -> None:
        from codetex_mcp.storage.files import delete_file

        fid = await upsert_file(db, repo_id, "src/cascade.py", "python", 10, 50, None)
        await upsert_symbol(
            db,
            fid,
            repo_id,
            "cascade_func",
            "function",
            "def cascade_func()",
            None,
            1,
            5,
            None,
            None,
            None,
        )
        await delete_file(db, fid)
        symbols = await list_symbols_by_file(db, fid)
        assert symbols == []
