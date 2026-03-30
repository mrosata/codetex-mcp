from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

import aiosqlite

from codetex_mcp.exceptions import DatabaseError
from codetex_mcp.storage.database import Database


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest_asyncio.fixture
async def db(db_path: Path) -> Database:  # type: ignore[misc]
    database = Database(db_path)
    await database.connect()
    yield database  # type: ignore[misc]
    await database.close()


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_file(self, db_path: Path) -> None:
        database = Database(db_path)
        await database.connect()
        assert db_path.exists()
        await database.close()

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, db: Database) -> None:
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "wal"

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, db: Database) -> None:
        cursor = await db.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_sqlite_vec_loaded(self, db: Database) -> None:
        cursor = await db.execute("SELECT vec_version()")
        row = await cursor.fetchone()
        assert row is not None
        assert isinstance(row[0], str)

    @pytest.mark.asyncio
    async def test_conn_property_before_connect_raises(self, db_path: Path) -> None:
        database = Database(db_path)
        with pytest.raises(DatabaseError, match="not connected"):
            _ = database.conn


class TestClose:
    @pytest.mark.asyncio
    async def test_close_sets_conn_none(self, db_path: Path) -> None:
        database = Database(db_path)
        await database.connect()
        await database.close()
        assert database._conn is None

    @pytest.mark.asyncio
    async def test_close_without_connect(self, db_path: Path) -> None:
        database = Database(db_path)
        await database.close()  # should not raise


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_cursor(self, db: Database) -> None:
        cursor = await db.execute("SELECT 1")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_executemany(self, db: Database) -> None:
        await db.execute("CREATE TABLE t (val INTEGER)")
        await db.executemany("INSERT INTO t (val) VALUES (?)", [(1,), (2,), (3,)])
        await db.conn.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM t")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 3


class TestMigrate:
    @pytest.mark.asyncio
    async def test_migration_creates_tables(self, db: Database) -> None:
        await db.migrate()

        # Check all 6 main tables exist
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'vec_%' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = [r[0] for r in rows]
        assert "schema_version" in table_names
        assert "repositories" in table_names
        assert "files" in table_names
        assert "symbols" in table_names
        assert "dependencies" in table_names
        assert "repo_overviews" in table_names

    @pytest.mark.asyncio
    async def test_migration_creates_vector_tables(self, db: Database) -> None:
        await db.migrate()

        # sqlite-vec virtual tables show up in sqlite_master
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'vec_%' ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = [r[0] for r in rows]
        assert "vec_file_embeddings" in table_names
        assert "vec_symbol_embeddings" in table_names

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, db: Database) -> None:
        await db.migrate()
        await db.migrate()  # should not raise

        cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1  # only one migration applied

    @pytest.mark.asyncio
    async def test_schema_version_recorded(self, db: Database) -> None:
        await db.migrate()

        cursor = await db.execute("SELECT version FROM schema_version ORDER BY version")
        rows = await cursor.fetchall()
        versions = [r[0] for r in rows]
        assert versions == [1]

    @pytest.mark.asyncio
    async def test_migration_creates_indexes(self, db: Database) -> None:
        await db.migrate()

        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%' ORDER BY name"
        )
        rows = await cursor.fetchall()
        index_names = [r[0] for r in rows]
        assert "idx_files_repo" in index_names
        assert "idx_files_repo_path" in index_names
        assert "idx_symbols_file" in index_names
        assert "idx_symbols_repo" in index_names
        assert "idx_symbols_name" in index_names
        assert "idx_deps_repo" in index_names
        assert "idx_deps_source" in index_names

    @pytest.mark.asyncio
    async def test_tables_have_correct_columns(self, db: Database) -> None:
        await db.migrate()

        # Check repositories table columns
        cursor = await db.execute("PRAGMA table_info(repositories)")
        rows = await cursor.fetchall()
        col_names = {r[1] for r in rows}
        assert col_names == {
            "id",
            "name",
            "remote_url",
            "local_path",
            "default_branch",
            "indexed_commit",
            "last_indexed_at",
            "created_at",
        }

        # Check files table columns
        cursor = await db.execute("PRAGMA table_info(files)")
        rows = await cursor.fetchall()
        col_names = {r[1] for r in rows}
        assert col_names == {
            "id",
            "repo_id",
            "path",
            "language",
            "lines_of_code",
            "token_count",
            "role",
            "summary",
            "imports_json",
            "updated_at",
        }

        # Check symbols table columns
        cursor = await db.execute("PRAGMA table_info(symbols)")
        rows = await cursor.fetchall()
        col_names = {r[1] for r in rows}
        assert col_names == {
            "id",
            "file_id",
            "repo_id",
            "name",
            "kind",
            "signature",
            "docstring",
            "summary",
            "start_line",
            "end_line",
            "parameters_json",
            "return_type",
            "calls_json",
            "updated_at",
        }

        # Check dependencies table columns
        cursor = await db.execute("PRAGMA table_info(dependencies)")
        rows = await cursor.fetchall()
        col_names = {r[1] for r in rows}
        assert col_names == {
            "id",
            "repo_id",
            "source_file_id",
            "target_path",
            "imported_names",
        }

        # Check repo_overviews table columns
        cursor = await db.execute("PRAGMA table_info(repo_overviews)")
        rows = await cursor.fetchall()
        col_names = {r[1] for r in rows}
        assert col_names == {
            "id",
            "repo_id",
            "overview",
            "directory_tree",
            "technologies",
            "commit_sha",
            "created_at",
        }

    @pytest.mark.asyncio
    async def test_fk_enforced_after_executescript_migration(
        self, db: Database
    ) -> None:
        """executescript() implicitly commits and can disable FK enforcement.
        Verify that PRAGMA foreign_keys remains ON after migration and that
        FK violations are rejected."""
        await db.migrate()

        # Confirm FK pragma is still on
        cursor = await db.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

        # Attempt to insert a file with a non-existent repo_id
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO files (repo_id, path) VALUES (?, ?)",
                (9999, "orphan.py"),
            )

    @pytest.mark.asyncio
    async def test_fk_blocks_invalid_symbol_file_id(self, db: Database) -> None:
        """Inserting a symbol with a non-existent file_id must raise FK error."""
        await db.migrate()

        # Insert a valid repo first
        await db.execute(
            "INSERT INTO repositories (name, local_path) VALUES (?, ?)",
            ("test-repo", "/tmp/test"),
        )
        await db.conn.commit()

        # Try to insert a symbol with invalid file_id
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO symbols (file_id, repo_id, name, kind, signature, start_line, end_line) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (9999, 1, "bad_func", "function", "def bad_func()", 1, 5),
            )

    @pytest.mark.asyncio
    async def test_foreign_key_cascade(self, db: Database) -> None:
        await db.migrate()

        # Insert a repo, a file, and a symbol
        await db.execute(
            "INSERT INTO repositories (name, local_path) VALUES (?, ?)",
            ("test-repo", "/tmp/test"),
        )
        await db.execute(
            "INSERT INTO files (repo_id, path) VALUES (?, ?)",
            (1, "src/main.py"),
        )
        await db.execute(
            "INSERT INTO symbols (file_id, repo_id, name, kind, signature, start_line, end_line) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "main", "function", "def main()", 1, 5),
        )
        await db.conn.commit()

        # Delete the repo — files and symbols should cascade
        await db.execute("DELETE FROM repositories WHERE id = 1")
        await db.conn.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM files")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0

        cursor = await db.execute("SELECT COUNT(*) FROM symbols")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0
