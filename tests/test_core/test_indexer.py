from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from codetex_mcp.analysis.models import (
    FileAnalysis,
    ImportInfo,
    ParameterInfo,
    SymbolInfo,
)
from codetex_mcp.analysis.parser import Parser
from codetex_mcp.config.settings import Settings
from codetex_mcp.core.indexer import (
    IndexResult,
    Indexer,
    _build_directory_tree,
    _extract_role,
    _imports_to_json,
    _params_to_json,
)
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.exceptions import IndexError  # noqa: A004
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.llm.provider import LLMProvider
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import Repository


# -- Fixtures -----------------------------------------------------------------


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


@pytest.fixture
def config(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        repos_dir=tmp_path / "data" / "repos",
        db_path=tmp_path / "test.db",
    )


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Create a fake repo directory with some source files."""
    repo = tmp_path / "my-repo"
    repo.mkdir()

    src = repo / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "import os\n\ndef main():\n    print('hello')\n\nmain()\n"
    )
    (src / "utils.py").write_text(
        "def helper(x: int) -> str:\n    return str(x)\n"
    )
    return repo


@pytest.fixture
def mock_git(repo_dir: Path) -> AsyncMock:
    git = AsyncMock(spec=GitOperations)
    git.list_tracked_files.return_value = ["src/main.py", "src/utils.py"]
    git.get_head_commit.return_value = "abc123def456"
    return git


@pytest.fixture
def mock_parser() -> MagicMock:
    parser = MagicMock(spec=Parser)

    def fake_parse(path: Path, content: str, language: str | None = None) -> FileAnalysis:
        if "main" in str(path):
            return FileAnalysis(
                path=str(path),
                language="python",
                imports=[ImportInfo(module="os", names=[])],
                symbols=[
                    SymbolInfo(
                        name="main",
                        kind="function",
                        signature="def main():",
                        start_line=3,
                        end_line=4,
                    ),
                ],
                lines_of_code=6,
                token_count=20,
            )
        return FileAnalysis(
            path=str(path),
            language="python",
            imports=[],
            symbols=[
                SymbolInfo(
                    name="helper",
                    kind="function",
                    signature="def helper(x: int) -> str:",
                    parameters=[ParameterInfo(name="x", type_annotation="int")],
                    return_type="str",
                    start_line=1,
                    end_line=2,
                ),
            ],
            lines_of_code=2,
            token_count=10,
        )

    parser.parse_file.side_effect = fake_parse
    return parser


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock(spec=LLMProvider)
    llm.summarize.return_value = "# Repository Overview\nThis is a test repo."
    llm.summarize_batch.side_effect = lambda prompts, **kwargs: [
        f"Summary for prompt {i}. Role: utility" for i in range(len(prompts))
    ]
    return llm


@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock(spec=Embedder)
    embedder.embed.return_value = [0.1] * 384
    embedder.embed_batch.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
    return embedder


@pytest_asyncio.fixture
async def repo_id(db: Database, repo_dir: Path) -> int:
    cursor = await db.execute(
        "INSERT INTO repositories (name, local_path, default_branch) "
        "VALUES (?, ?, ?)",
        ("my-repo", str(repo_dir), "main"),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@pytest.fixture
def repo_record(repo_id: int, repo_dir: Path) -> Repository:
    return Repository(
        id=repo_id,
        name="my-repo",
        remote_url=None,
        local_path=str(repo_dir),
        default_branch="main",
        indexed_commit=None,
        last_indexed_at=None,
        created_at="2024-01-01T00:00:00",
    )


@pytest.fixture
def indexer(
    db: Database,
    mock_git: AsyncMock,
    mock_parser: MagicMock,
    mock_llm: AsyncMock,
    mock_embedder: MagicMock,
    config: Settings,
) -> Indexer:
    return Indexer(
        db=db,
        git=mock_git,
        parser=mock_parser,
        llm=mock_llm,
        embedder=mock_embedder,
        config=config,
    )


# -- Constructor ---------------------------------------------------------------


class TestIndexerInit:
    def test_stores_dependencies(
        self,
        db: Database,
        mock_git: AsyncMock,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
    ) -> None:
        idx = Indexer(db, mock_git, mock_parser, mock_llm, mock_embedder, config)
        assert idx._db is db
        assert idx._git is mock_git
        assert idx._parser is mock_parser
        assert idx._llm is mock_llm
        assert idx._embedder is mock_embedder
        assert idx._config is config


# -- Full Index Pipeline ------------------------------------------------------


class TestFullIndex:
    @pytest.mark.asyncio
    async def test_full_index_returns_result(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record)
        assert isinstance(result, IndexResult)
        assert result.files_indexed == 2
        assert result.symbols_extracted == 2
        assert result.commit_sha == "abc123def456"
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_full_index_stores_files(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT path, language, lines_of_code, token_count FROM files "
            "WHERE repo_id = ? ORDER BY path",
            (repo_record.id,),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "src/main.py"
        assert rows[0][1] == "python"
        assert rows[0][2] == 6  # lines_of_code
        assert rows[0][3] == 20  # token_count
        assert rows[1][0] == "src/utils.py"

    @pytest.mark.asyncio
    async def test_full_index_stores_symbols(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT name, kind, signature FROM symbols "
            "WHERE repo_id = ? ORDER BY name",
            (repo_record.id,),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 2
        names = {row[0] for row in rows}
        assert names == {"main", "helper"}

    @pytest.mark.asyncio
    async def test_full_index_stores_dependencies(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT target_path FROM dependencies WHERE repo_id = ?",
            (repo_record.id,),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "os"

    @pytest.mark.asyncio
    async def test_full_index_calls_llm_tier2(
        self, indexer: Indexer, repo_record: Repository, mock_llm: AsyncMock,
    ) -> None:
        await indexer.index(repo_record)
        # Tier 2: one call per file (batch)
        assert mock_llm.summarize_batch.call_count >= 1
        first_call = mock_llm.summarize_batch.call_args_list[0]
        prompts = first_call[0][0]
        assert len(prompts) == 2  # 2 files

    @pytest.mark.asyncio
    async def test_full_index_calls_llm_tier3(
        self, indexer: Indexer, repo_record: Repository, mock_llm: AsyncMock,
    ) -> None:
        await indexer.index(repo_record)
        # Tier 3: second batch call for summarizable symbols
        assert mock_llm.summarize_batch.call_count >= 2
        second_call = mock_llm.summarize_batch.call_args_list[1]
        prompts = second_call[0][0]
        assert len(prompts) == 2  # 2 functions

    @pytest.mark.asyncio
    async def test_full_index_calls_llm_tier1(
        self, indexer: Indexer, repo_record: Repository, mock_llm: AsyncMock,
    ) -> None:
        await indexer.index(repo_record)
        # Tier 1: single summarize call
        assert mock_llm.summarize.call_count == 1

    @pytest.mark.asyncio
    async def test_full_index_stores_tier2_summaries(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT summary, role FROM files WHERE repo_id = ? ORDER BY path",
            (repo_record.id,),
        )
        rows = await cursor.fetchall()
        assert all(row[0] is not None for row in rows)
        assert all(row[1] is not None for row in rows)

    @pytest.mark.asyncio
    async def test_full_index_stores_tier3_summaries(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT summary FROM symbols WHERE repo_id = ?",
            (repo_record.id,),
        )
        rows = await cursor.fetchall()
        assert all(row[0] is not None for row in rows)

    @pytest.mark.asyncio
    async def test_full_index_generates_embeddings(
        self, indexer: Indexer, repo_record: Repository, mock_embedder: MagicMock,
    ) -> None:
        await indexer.index(repo_record)
        # embed_batch called for files and symbols
        assert mock_embedder.embed_batch.call_count == 2

    @pytest.mark.asyncio
    async def test_full_index_stores_file_embeddings(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM vec_file_embeddings",
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 2  # 2 files

    @pytest.mark.asyncio
    async def test_full_index_stores_symbol_embeddings(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM vec_symbol_embeddings",
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 2  # 2 symbols

    @pytest.mark.asyncio
    async def test_full_index_stores_repo_overview(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT overview, commit_sha FROM repo_overviews WHERE repo_id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "# Repository Overview\nThis is a test repo."
        assert row[1] == "abc123def456"

    @pytest.mark.asyncio
    async def test_full_index_updates_indexed_commit(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT indexed_commit, last_indexed_at FROM repositories WHERE id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "abc123def456"
        assert row[1] is not None  # last_indexed_at set

    @pytest.mark.asyncio
    async def test_full_index_llm_calls_count(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record)
        # 2 files (Tier 2) + 2 functions (Tier 3) + 1 (Tier 1) = 5
        assert result.llm_calls_made == 5

    @pytest.mark.asyncio
    async def test_full_index_token_count(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record)
        assert result.tokens_used == 30  # 20 + 10


# -- Dry Run ------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_estimates(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record, dry_run=True)
        assert isinstance(result, IndexResult)
        assert result.files_indexed == 2
        assert result.symbols_extracted == 2
        assert result.commit_sha == "(dry run)"

    @pytest.mark.asyncio
    async def test_dry_run_estimates_llm_calls(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record, dry_run=True)
        # 2 files (Tier 2) + 2 functions (Tier 3) + 1 (Tier 1) = 5
        assert result.llm_calls_made == 5

    @pytest.mark.asyncio
    async def test_dry_run_no_llm_calls(
        self, indexer: Indexer, repo_record: Repository, mock_llm: AsyncMock,
    ) -> None:
        await indexer.index(repo_record, dry_run=True)
        mock_llm.summarize.assert_not_called()
        mock_llm.summarize_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record, dry_run=True)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_dry_run_no_embeddings(
        self, indexer: Indexer, repo_record: Repository, mock_embedder: MagicMock,
    ) -> None:
        await indexer.index(repo_record, dry_run=True)
        mock_embedder.embed_batch.assert_not_called()


# -- Path Filter --------------------------------------------------------------


class TestPathFilter:
    @pytest.mark.asyncio
    async def test_path_filter_restricts_files(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record, path_filter="src/main")
        assert result.files_indexed == 1

    @pytest.mark.asyncio
    async def test_path_filter_no_match(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        result = await indexer.index(repo_record, path_filter="nonexistent/")
        assert result.files_indexed == 0


# -- Progress Callback --------------------------------------------------------


class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_on_progress_called(
        self, indexer: Indexer, repo_record: Repository,
    ) -> None:
        calls: list[tuple[int, int, str]] = []

        def on_progress(current: int, total: int, path: str) -> None:
            calls.append((current, total, path))

        await indexer.index(repo_record, dry_run=True, on_progress=on_progress)
        assert len(calls) == 2
        assert calls[0] == (1, 2, "src/main.py")
        assert calls[1] == (2, 2, "src/utils.py")


# -- Error Handling -----------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_wraps_unexpected_errors(
        self,
        db: Database,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
        repo_record: Repository,
    ) -> None:
        git = AsyncMock(spec=GitOperations)
        git.list_tracked_files.side_effect = RuntimeError("git broke")
        idx = Indexer(db, git, mock_parser, mock_llm, mock_embedder, config)

        with pytest.raises(IndexError, match="Indexing failed.*git broke"):
            await idx.index(repo_record)

    @pytest.mark.asyncio
    async def test_does_not_wrap_index_error(
        self,
        db: Database,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
        repo_record: Repository,
    ) -> None:
        git = AsyncMock(spec=GitOperations)
        git.list_tracked_files.side_effect = IndexError("already an IndexError")
        idx = Indexer(db, git, mock_parser, mock_llm, mock_embedder, config)

        with pytest.raises(IndexError, match="already an IndexError"):
            await idx.index(repo_record)


# -- Tier 3 Skipping Non-summarizable Symbols --------------------------------


class TestTier3SymbolFiltering:
    @pytest.mark.asyncio
    async def test_skips_variable_symbols(
        self,
        db: Database,
        mock_git: AsyncMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
        repo_record: Repository,
        repo_dir: Path,
    ) -> None:
        parser = MagicMock(spec=Parser)
        parser.parse_file.return_value = FileAnalysis(
            path="src/consts.py",
            language="python",
            imports=[],
            symbols=[
                SymbolInfo(
                    name="MAX_SIZE",
                    kind="variable",
                    signature="MAX_SIZE = 100",
                    start_line=1,
                    end_line=1,
                ),
            ],
            lines_of_code=1,
            token_count=5,
        )
        # Override tracked files to return single file
        mock_git.list_tracked_files.return_value = ["src/consts.py"]
        (repo_dir / "src" / "consts.py").write_text("MAX_SIZE = 100\n")

        idx = Indexer(db, mock_git, parser, mock_llm, mock_embedder, config)
        result = await idx.index(repo_record)

        # Tier 2: 1 file. Tier 3: 0 (variable skipped). Tier 1: 1.
        assert result.llm_calls_made == 2
        # The second batch call (Tier 3) should not have been made
        assert mock_llm.summarize_batch.call_count == 1  # only Tier 2


# -- Re-index (idempotent) ---------------------------------------------------


class TestReindex:
    @pytest.mark.asyncio
    async def test_reindex_upserts_not_duplicates(
        self, indexer: Indexer, repo_record: Repository, db: Database,
    ) -> None:
        await indexer.index(repo_record)
        await indexer.index(repo_record)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 2  # still 2, not 4


# -- Helper Functions ---------------------------------------------------------


class TestHelpers:
    def test_imports_to_json(self) -> None:
        imports = [
            ImportInfo(module="os", names=["path"]),
            ImportInfo(module="sys", names=[]),
        ]
        result = _imports_to_json(imports)
        import json

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["module"] == "os"
        assert parsed[0]["names"] == ["path"]
        assert parsed[1]["module"] == "sys"
        assert parsed[1]["names"] == []

    def test_params_to_json(self) -> None:
        params = [
            ParameterInfo(name="x", type_annotation="int", default_value=None),
            ParameterInfo(name="y", type_annotation="str", default_value="'hello'"),
        ]
        result = _params_to_json(params)
        import json

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "x"
        assert parsed[0]["type"] == "int"
        assert parsed[0]["default"] is None
        assert parsed[1]["default"] == "'hello'"

    def test_extract_role_entry_point(self) -> None:
        assert _extract_role("This is an entry_point for the CLI.") == "entry_point"

    def test_extract_role_core_logic(self) -> None:
        assert _extract_role("Contains core_logic for indexing.") == "core_logic"

    def test_extract_role_default_utility(self) -> None:
        assert _extract_role("Some random text without role keywords.") == "utility"

    def test_extract_role_case_insensitive(self) -> None:
        assert _extract_role("This is CORE_LOGIC.") == "core_logic"

    def test_build_directory_tree_empty(self) -> None:
        assert _build_directory_tree([]) == "(empty)"

    def test_build_directory_tree_single_file(self) -> None:
        result = _build_directory_tree(["main.py"])
        assert "main.py" in result

    def test_build_directory_tree_nested(self) -> None:
        result = _build_directory_tree(["src/a.py", "src/b.py", "README.md"])
        assert "src" in result
        assert "a.py" in result
        assert "b.py" in result
        assert "README.md" in result


# -- IndexResult dataclass ---------------------------------------------------


class TestIndexResult:
    def test_fields(self) -> None:
        result = IndexResult(
            files_indexed=10,
            symbols_extracted=50,
            llm_calls_made=15,
            tokens_used=5000,
            duration_seconds=1.5,
            commit_sha="abc123",
        )
        assert result.files_indexed == 10
        assert result.symbols_extracted == 50
        assert result.llm_calls_made == 15
        assert result.tokens_used == 5000
        assert result.duration_seconds == 1.5
        assert result.commit_sha == "abc123"
