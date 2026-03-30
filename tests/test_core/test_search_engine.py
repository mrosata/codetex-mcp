from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from codetex_mcp.core.search_engine import SearchEngine, SearchResult
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.storage.database import Database


def _make_embedding(seed: float) -> list[float]:
    """Create a deterministic 384-dim embedding for testing."""
    return [seed + i * 0.001 for i in range(384)]


def _serialize_f32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


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
    cursor = await db.execute(
        "INSERT INTO repositories (name, local_path, default_branch) VALUES (?, ?, ?)",
        ("test-repo", "/tmp/test-repo", "main"),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock(spec=Embedder)
    embedder.embed.return_value = _make_embedding(1.0)
    return embedder


@pytest_asyncio.fixture
async def engine(db: Database, mock_embedder: MagicMock) -> SearchEngine:
    return SearchEngine(db, mock_embedder)


async def _insert_file_with_embedding(
    db: Database, repo_id: int, path: str, summary: str | None, embedding_seed: float
) -> int:
    """Insert a file record and its embedding, return file_id."""
    cursor = await db.execute(
        "INSERT INTO files (repo_id, path, language, lines_of_code, token_count, summary) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (repo_id, path, "python", 50, 200, summary),
    )
    file_id = cursor.lastrowid
    assert file_id is not None
    embedding = _make_embedding(embedding_seed)
    await db.execute(
        "INSERT INTO vec_file_embeddings (file_id, embedding) VALUES (?, ?)",
        (file_id, _serialize_f32(embedding)),
    )
    await db.conn.commit()
    return file_id


async def _insert_symbol_with_embedding(
    db: Database,
    repo_id: int,
    file_id: int,
    name: str,
    summary: str | None,
    embedding_seed: float,
) -> int:
    """Insert a symbol record and its embedding, return symbol_id."""
    cursor = await db.execute(
        "INSERT INTO symbols (file_id, repo_id, name, kind, signature, "
        "summary, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (file_id, repo_id, name, "function", f"def {name}():", summary, 1, 10),
    )
    symbol_id = cursor.lastrowid
    assert symbol_id is not None
    embedding = _make_embedding(embedding_seed)
    await db.execute(
        "INSERT INTO vec_symbol_embeddings (symbol_id, embedding) VALUES (?, ?)",
        (symbol_id, _serialize_f32(embedding)),
    )
    await db.conn.commit()
    return symbol_id


# -- Search -----------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_empty_index_returns_empty(
        self, engine: SearchEngine, repo_id: int
    ) -> None:
        results = await engine.search(repo_id, "how does auth work")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_file_results(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        await _insert_file_with_embedding(
            db, repo_id, "src/auth.py", "Handles authentication", 1.0
        )
        await _insert_file_with_embedding(
            db, repo_id, "src/utils.py", "Utility functions", 2.0
        )

        results = await engine.search(repo_id, "authentication")
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.kind == "file" for r in results)

    @pytest.mark.asyncio
    async def test_returns_symbol_results(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        file_id = await _insert_file_with_embedding(
            db, repo_id, "src/auth.py", "Auth module", 5.0
        )
        await _insert_symbol_with_embedding(
            db, repo_id, file_id, "login", "Login handler", 1.0
        )

        results = await engine.search(repo_id, "login")
        assert any(r.kind == "symbol" for r in results)
        symbol_result = next(r for r in results if r.kind == "symbol")
        assert symbol_result.name == "login"
        assert symbol_result.summary == "Login handler"
        assert symbol_result.path == "src/auth.py"

    @pytest.mark.asyncio
    async def test_merges_file_and_symbol_results(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        file_id = await _insert_file_with_embedding(
            db, repo_id, "src/auth.py", "Auth module", 2.0
        )
        await _insert_symbol_with_embedding(
            db, repo_id, file_id, "login", "Login function", 1.5
        )

        results = await engine.search(repo_id, "auth")
        assert len(results) >= 2
        kinds = {r.kind for r in results}
        assert "file" in kinds
        assert "symbol" in kinds

    @pytest.mark.asyncio
    async def test_results_sorted_by_score(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        await _insert_file_with_embedding(db, repo_id, "src/a.py", "A file", 1.0)
        await _insert_file_with_embedding(db, repo_id, "src/b.py", "B file", 3.0)
        await _insert_file_with_embedding(db, repo_id, "src/c.py", "C file", 2.0)

        results = await engine.search(repo_id, "query")
        scores = [r.score for r in results]
        assert scores == sorted(scores)

    @pytest.mark.asyncio
    async def test_respects_max_results(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        for i in range(5):
            await _insert_file_with_embedding(
                db, repo_id, f"src/file{i}.py", f"File {i}", float(i)
            )

        results = await engine.search(repo_id, "query", max_results=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_calls_embedder_with_query(
        self, engine: SearchEngine, db: Database, repo_id: int, mock_embedder: MagicMock
    ) -> None:
        await engine.search(repo_id, "how does auth work")
        mock_embedder.embed.assert_called_once_with("how does auth work")

    @pytest.mark.asyncio
    async def test_handles_null_summary(
        self, engine: SearchEngine, db: Database, repo_id: int
    ) -> None:
        await _insert_file_with_embedding(db, repo_id, "src/empty.py", None, 1.0)

        results = await engine.search(repo_id, "query")
        assert len(results) == 1
        assert results[0].summary == ""


class TestSearchResult:
    def test_dataclass_fields(self) -> None:
        result = SearchResult(
            kind="file",
            path="src/main.py",
            name="src/main.py",
            summary="Main module",
            score=0.123,
        )
        assert result.kind == "file"
        assert result.path == "src/main.py"
        assert result.name == "src/main.py"
        assert result.summary == "Main module"
        assert result.score == 0.123

    def test_symbol_result(self) -> None:
        result = SearchResult(
            kind="symbol",
            path="src/auth.py",
            name="login",
            summary="Login handler",
            score=0.456,
        )
        assert result.kind == "symbol"
        assert result.name == "login"
        assert result.path == "src/auth.py"
