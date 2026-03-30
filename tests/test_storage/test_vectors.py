from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.storage.database import Database
from codetex_mcp.storage.files import upsert_file
from codetex_mcp.storage.repositories import create_repo
from codetex_mcp.storage.symbols import upsert_symbol
from codetex_mcp.storage.vectors import (
    delete_file_embedding,
    delete_symbol_embedding,
    search_file_embeddings,
    search_symbol_embeddings,
    upsert_file_embedding,
    upsert_symbol_embedding,
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


@pytest_asyncio.fixture
async def symbol_id(db: Database, repo_id: int, file_id: int) -> int:  # type: ignore[misc]
    return await upsert_symbol(
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


def _make_embedding(seed: float = 0.1) -> list[float]:
    """Create a 384-dim embedding with deterministic values."""
    return [seed + i * 0.001 for i in range(384)]


class TestUpsertFileEmbedding:
    @pytest.mark.asyncio
    async def test_insert_file_embedding(self, db: Database, file_id: int) -> None:
        embedding = _make_embedding(0.1)
        await upsert_file_embedding(db, file_id, embedding)

        # Verify it was stored by searching for it
        results = await search_file_embeddings(db, embedding, limit=1)
        assert len(results) == 1
        assert results[0][0] == file_id

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(self, db: Database, file_id: int) -> None:
        embedding1 = _make_embedding(0.1)
        embedding2 = _make_embedding(0.5)
        await upsert_file_embedding(db, file_id, embedding1)
        await upsert_file_embedding(db, file_id, embedding2)

        # Search with the new embedding — should find the file
        results = await search_file_embeddings(db, embedding2, limit=1)
        assert len(results) == 1
        assert results[0][0] == file_id


class TestUpsertSymbolEmbedding:
    @pytest.mark.asyncio
    async def test_insert_symbol_embedding(self, db: Database, symbol_id: int) -> None:
        embedding = _make_embedding(0.2)
        await upsert_symbol_embedding(db, symbol_id, embedding)

        results = await search_symbol_embeddings(db, embedding, limit=1)
        assert len(results) == 1
        assert results[0][0] == symbol_id

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(self, db: Database, symbol_id: int) -> None:
        embedding1 = _make_embedding(0.2)
        embedding2 = _make_embedding(0.7)
        await upsert_symbol_embedding(db, symbol_id, embedding1)
        await upsert_symbol_embedding(db, symbol_id, embedding2)

        results = await search_symbol_embeddings(db, embedding2, limit=1)
        assert len(results) == 1
        assert results[0][0] == symbol_id


class TestDeleteFileEmbedding:
    @pytest.mark.asyncio
    async def test_delete_removes_embedding(self, db: Database, file_id: int) -> None:
        embedding = _make_embedding(0.1)
        await upsert_file_embedding(db, file_id, embedding)
        await delete_file_embedding(db, file_id)

        results = await search_file_embeddings(db, embedding, limit=10)
        file_ids = [r[0] for r in results]
        assert file_id not in file_ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self, db: Database) -> None:
        await delete_file_embedding(db, 9999)


class TestDeleteSymbolEmbedding:
    @pytest.mark.asyncio
    async def test_delete_removes_embedding(self, db: Database, symbol_id: int) -> None:
        embedding = _make_embedding(0.2)
        await upsert_symbol_embedding(db, symbol_id, embedding)
        await delete_symbol_embedding(db, symbol_id)

        results = await search_symbol_embeddings(db, embedding, limit=10)
        symbol_ids = [r[0] for r in results]
        assert symbol_id not in symbol_ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self, db: Database) -> None:
        await delete_symbol_embedding(db, 9999)


class TestSearchFileEmbeddings:
    @pytest.mark.asyncio
    async def test_search_returns_nearest_neighbors(
        self, db: Database, repo_id: int
    ) -> None:
        # Create 3 files with different embeddings
        fid1 = await upsert_file(db, repo_id, "a.py", "python", 10, 50, None)
        fid2 = await upsert_file(db, repo_id, "b.py", "python", 20, 100, None)
        fid3 = await upsert_file(db, repo_id, "c.py", "python", 30, 150, None)

        emb1 = _make_embedding(0.1)
        emb2 = _make_embedding(0.5)
        emb3 = _make_embedding(0.9)

        await upsert_file_embedding(db, fid1, emb1)
        await upsert_file_embedding(db, fid2, emb2)
        await upsert_file_embedding(db, fid3, emb3)

        # Search with a query close to emb1
        query = _make_embedding(0.1)
        results = await search_file_embeddings(db, query, limit=3)

        assert len(results) == 3
        # Nearest should be fid1 (exact match)
        assert results[0][0] == fid1
        # Distances should be in ascending order
        assert results[0][1] <= results[1][1] <= results[2][1]

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, db: Database, repo_id: int) -> None:
        fid1 = await upsert_file(db, repo_id, "a.py", "python", 10, 50, None)
        fid2 = await upsert_file(db, repo_id, "b.py", "python", 20, 100, None)

        await upsert_file_embedding(db, fid1, _make_embedding(0.1))
        await upsert_file_embedding(db, fid2, _make_embedding(0.5))

        results = await search_file_embeddings(db, _make_embedding(0.1), limit=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_empty_table_returns_empty(self, db: Database) -> None:
        results = await search_file_embeddings(db, _make_embedding(0.1), limit=10)
        assert results == []


class TestSearchSymbolEmbeddings:
    @pytest.mark.asyncio
    async def test_search_returns_nearest_neighbors(
        self, db: Database, repo_id: int, file_id: int
    ) -> None:
        sid1 = await upsert_symbol(
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
        sid2 = await upsert_symbol(
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
        sid3 = await upsert_symbol(
            db,
            file_id,
            repo_id,
            "func_c",
            "function",
            "def func_c()",
            None,
            20,
            25,
            None,
            None,
            None,
        )

        emb1 = _make_embedding(0.1)
        emb2 = _make_embedding(0.5)
        emb3 = _make_embedding(0.9)

        await upsert_symbol_embedding(db, sid1, emb1)
        await upsert_symbol_embedding(db, sid2, emb2)
        await upsert_symbol_embedding(db, sid3, emb3)

        query = _make_embedding(0.9)
        results = await search_symbol_embeddings(db, query, limit=3)

        assert len(results) == 3
        # Nearest should be sid3 (exact match)
        assert results[0][0] == sid3
        assert results[0][1] <= results[1][1] <= results[2][1]

    @pytest.mark.asyncio
    async def test_search_empty_table_returns_empty(self, db: Database) -> None:
        results = await search_symbol_embeddings(db, _make_embedding(0.2), limit=10)
        assert results == []
