from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.storage.database import Database
from codetex_mcp.storage.files import (
    FileRecord,
    count_files,
    delete_dependencies_by_file,
    delete_file,
    get_file,
    get_total_tokens,
    list_files,
    update_file_summary,
    upsert_dependency,
    upsert_file,
)
from codetex_mcp.storage.repositories import create_repo


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


class TestUpsertFile:
    @pytest.mark.asyncio
    async def test_upsert_returns_file_id(self, db: Database, repo_id: int) -> None:
        file_id = await upsert_file(
            db, repo_id, "src/main.py", "python", 100, 500, None
        )
        assert file_id > 0

    @pytest.mark.asyncio
    async def test_upsert_stores_all_fields(self, db: Database, repo_id: int) -> None:
        imports = json.dumps([{"module": "os", "names": ["path"]}])
        await upsert_file(db, repo_id, "src/app.py", "python", 50, 250, imports)
        record = await get_file(db, repo_id, "src/app.py")
        assert record is not None
        assert isinstance(record, FileRecord)
        assert record.repo_id == repo_id
        assert record.path == "src/app.py"
        assert record.language == "python"
        assert record.lines_of_code == 50
        assert record.token_count == 250
        assert record.imports_json == imports
        assert record.role is None
        assert record.summary is None
        assert record.updated_at is not None

    @pytest.mark.asyncio
    async def test_upsert_updates_on_conflict(self, db: Database, repo_id: int) -> None:
        await upsert_file(db, repo_id, "src/lib.py", "python", 10, 50, None)
        await upsert_file(db, repo_id, "src/lib.py", "python", 20, 100, '["os"]')
        record = await get_file(db, repo_id, "src/lib.py")
        assert record is not None
        assert record.lines_of_code == 20
        assert record.token_count == 100
        assert record.imports_json == '["os"]'


class TestUpdateFileSummary:
    @pytest.mark.asyncio
    async def test_update_sets_summary_and_role(
        self, db: Database, repo_id: int
    ) -> None:
        file_id = await upsert_file(
            db, repo_id, "src/model.py", "python", 30, 150, None
        )
        await update_file_summary(db, file_id, "Defines the User model", "model")
        record = await get_file(db, repo_id, "src/model.py")
        assert record is not None
        assert record.summary == "Defines the User model"
        assert record.role == "model"


class TestGetFile:
    @pytest.mark.asyncio
    async def test_get_existing_file(self, db: Database, repo_id: int) -> None:
        await upsert_file(db, repo_id, "README.md", None, 20, 80, None)
        record = await get_file(db, repo_id, "README.md")
        assert record is not None
        assert record.path == "README.md"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(
        self, db: Database, repo_id: int
    ) -> None:
        result = await get_file(db, repo_id, "no/such/file.py")
        assert result is None


class TestListFiles:
    @pytest.mark.asyncio
    async def test_list_empty(self, db: Database, repo_id: int) -> None:
        files = await list_files(db, repo_id)
        assert files == []

    @pytest.mark.asyncio
    async def test_list_multiple_ordered_by_path(
        self, db: Database, repo_id: int
    ) -> None:
        await upsert_file(db, repo_id, "src/z.py", "python", 10, 50, None)
        await upsert_file(db, repo_id, "src/a.py", "python", 20, 100, None)
        files = await list_files(db, repo_id)
        assert len(files) == 2
        assert files[0].path == "src/a.py"
        assert files[1].path == "src/z.py"


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_delete_removes_file(self, db: Database, repo_id: int) -> None:
        file_id = await upsert_file(db, repo_id, "del.py", "python", 5, 25, None)
        await delete_file(db, file_id)
        result = await get_file(db, repo_id, "del.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(
        self, db: Database, repo_id: int
    ) -> None:
        await delete_file(db, 9999)


class TestCountFiles:
    @pytest.mark.asyncio
    async def test_count_empty(self, db: Database, repo_id: int) -> None:
        count = await count_files(db, repo_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_multiple(self, db: Database, repo_id: int) -> None:
        await upsert_file(db, repo_id, "a.py", "python", 10, 50, None)
        await upsert_file(db, repo_id, "b.py", "python", 20, 100, None)
        count = await count_files(db, repo_id)
        assert count == 2


class TestGetTotalTokens:
    @pytest.mark.asyncio
    async def test_total_tokens_empty(self, db: Database, repo_id: int) -> None:
        total = await get_total_tokens(db, repo_id)
        assert total == 0

    @pytest.mark.asyncio
    async def test_total_tokens_sum(self, db: Database, repo_id: int) -> None:
        await upsert_file(db, repo_id, "a.py", "python", 10, 200, None)
        await upsert_file(db, repo_id, "b.py", "python", 20, 300, None)
        total = await get_total_tokens(db, repo_id)
        assert total == 500


class TestDependencies:
    @pytest.mark.asyncio
    async def test_upsert_dependency(self, db: Database, repo_id: int) -> None:
        file_id = await upsert_file(db, repo_id, "src/app.py", "python", 10, 50, None)
        await upsert_dependency(db, repo_id, file_id, "src/utils.py", '["helper"]')
        # Verify via raw query
        cursor = await db.execute(
            "SELECT target_path, imported_names FROM dependencies WHERE source_file_id = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "src/utils.py"
        assert row[1] == '["helper"]'

    @pytest.mark.asyncio
    async def test_upsert_dependency_updates_on_conflict(
        self, db: Database, repo_id: int
    ) -> None:
        file_id = await upsert_file(db, repo_id, "src/app.py", "python", 10, 50, None)
        await upsert_dependency(db, repo_id, file_id, "src/utils.py", '["a"]')
        await upsert_dependency(db, repo_id, file_id, "src/utils.py", '["a", "b"]')
        cursor = await db.execute(
            "SELECT imported_names FROM dependencies WHERE source_file_id = ? AND target_path = ?",
            (file_id, "src/utils.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == '["a", "b"]'

    @pytest.mark.asyncio
    async def test_delete_dependencies_by_file(
        self, db: Database, repo_id: int
    ) -> None:
        file_id = await upsert_file(db, repo_id, "src/app.py", "python", 10, 50, None)
        await upsert_dependency(db, repo_id, file_id, "src/utils.py", None)
        await upsert_dependency(db, repo_id, file_id, "src/models.py", None)
        await delete_dependencies_by_file(db, file_id)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM dependencies WHERE source_file_id = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_file_delete_cascades_dependencies(
        self, db: Database, repo_id: int
    ) -> None:
        file_id = await upsert_file(db, repo_id, "src/app.py", "python", 10, 50, None)
        await upsert_dependency(db, repo_id, file_id, "src/utils.py", None)
        await delete_file(db, file_id)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM dependencies WHERE source_file_id = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0
