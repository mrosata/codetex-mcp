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
from codetex_mcp.core.syncer import SyncResult, Syncer
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.exceptions import IndexError  # noqa: A004
from codetex_mcp.git.operations import DiffResult, GitOperations
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
        tier1_rebuild_threshold=0.10,
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
    (src / "utils.py").write_text("def helper(x: int) -> str:\n    return str(x)\n")
    return repo


@pytest.fixture
def mock_git(repo_dir: Path) -> AsyncMock:
    git = AsyncMock(spec=GitOperations)
    git.get_head_commit.return_value = "new_commit_sha"
    git.diff_commits.return_value = DiffResult(
        added=["src/new_file.py"],
        modified=["src/main.py"],
        deleted=["src/old_file.py"],
        renamed=[],
    )
    return git


@pytest.fixture
def mock_parser() -> MagicMock:
    parser = MagicMock(spec=Parser)

    def fake_parse(
        path: Path, content: str, language: str | None = None
    ) -> FileAnalysis:
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
        if "new_file" in str(path):
            return FileAnalysis(
                path=str(path),
                language="python",
                imports=[],
                symbols=[
                    SymbolInfo(
                        name="new_func",
                        kind="function",
                        signature="def new_func():",
                        start_line=1,
                        end_line=2,
                    ),
                ],
                lines_of_code=2,
                token_count=8,
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
        "INSERT INTO repositories (name, local_path, default_branch, indexed_commit) "
        "VALUES (?, ?, ?, ?)",
        ("my-repo", str(repo_dir), "main", "old_commit_sha"),
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
        indexed_commit="old_commit_sha",
        last_indexed_at=None,
        created_at="2024-01-01T00:00:00",
    )


@pytest_asyncio.fixture
async def indexed_repo(
    db: Database,
    repo_id: int,
    repo_dir: Path,
) -> None:
    """Pre-populate the DB with file/symbol/embedding records to simulate a prior index."""
    # Insert old_file.py
    cursor = await db.execute(
        "INSERT INTO files (repo_id, path, language, lines_of_code, token_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (repo_id, "src/old_file.py", "python", 10, 50),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    old_file_id = cursor.lastrowid

    # Insert a symbol for old_file.py
    cursor = await db.execute(
        "INSERT INTO symbols (file_id, repo_id, name, kind, signature, start_line, end_line, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (old_file_id, repo_id, "old_func", "function", "def old_func():", 1, 3),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    old_symbol_id = cursor.lastrowid

    # Insert embeddings (using raw bytes)
    import struct

    embedding = struct.pack(f"{384}f", *([0.5] * 384))
    await db.execute(
        "INSERT INTO vec_file_embeddings(file_id, embedding) VALUES (?, ?)",
        (old_file_id, embedding),
    )
    await db.execute(
        "INSERT INTO vec_symbol_embeddings(symbol_id, embedding) VALUES (?, ?)",
        (old_symbol_id, embedding),
    )
    await db.conn.commit()

    # Insert main.py (will be modified)
    cursor = await db.execute(
        "INSERT INTO files (repo_id, path, language, lines_of_code, token_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (repo_id, "src/main.py", "python", 5, 15),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    main_file_id = cursor.lastrowid

    cursor = await db.execute(
        "INSERT INTO symbols (file_id, repo_id, name, kind, signature, start_line, end_line, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (main_file_id, repo_id, "main", "function", "def main():", 3, 4),
    )
    await db.conn.commit()


@pytest.fixture
def syncer(
    db: Database,
    mock_git: AsyncMock,
    mock_parser: MagicMock,
    mock_llm: AsyncMock,
    mock_embedder: MagicMock,
    config: Settings,
) -> Syncer:
    return Syncer(
        db=db,
        git=mock_git,
        parser=mock_parser,
        llm=mock_llm,
        embedder=mock_embedder,
        config=config,
    )


# -- Constructor ---------------------------------------------------------------


class TestSyncerInit:
    def test_stores_dependencies(
        self,
        db: Database,
        mock_git: AsyncMock,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
    ) -> None:
        s = Syncer(db, mock_git, mock_parser, mock_llm, mock_embedder, config)
        assert s._db is db
        assert s._git is mock_git
        assert s._parser is mock_parser
        assert s._llm is mock_llm
        assert s._embedder is mock_embedder
        assert s._config is config


# -- Already Current -----------------------------------------------------------


class TestAlreadyCurrent:
    @pytest.mark.asyncio
    async def test_returns_already_current_when_same_commit(
        self,
        syncer: Syncer,
        repo_record: Repository,
        mock_git: AsyncMock,
    ) -> None:
        mock_git.get_head_commit.return_value = "old_commit_sha"
        result = await syncer.sync(repo_record)

        assert isinstance(result, SyncResult)
        assert result.already_current is True
        assert result.files_added == 0
        assert result.files_modified == 0
        assert result.files_deleted == 0
        assert result.llm_calls_made == 0
        assert result.tier1_rebuilt is False
        assert result.old_commit == "old_commit_sha"
        assert result.new_commit == "old_commit_sha"

    @pytest.mark.asyncio
    async def test_no_diff_called_when_current(
        self,
        syncer: Syncer,
        repo_record: Repository,
        mock_git: AsyncMock,
    ) -> None:
        mock_git.get_head_commit.return_value = "old_commit_sha"
        await syncer.sync(repo_record)
        mock_git.diff_commits.assert_not_called()


# -- Full Sync Pipeline -------------------------------------------------------


class TestFullSync:
    @pytest.mark.asyncio
    async def test_sync_returns_result(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        repo_dir: Path,
    ) -> None:
        # Create new_file.py on disk
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")

        result = await syncer.sync(repo_record)

        assert isinstance(result, SyncResult)
        assert result.already_current is False
        assert result.files_added == 1
        assert result.files_modified == 1
        assert result.files_deleted == 1
        assert result.old_commit == "old_commit_sha"
        assert result.new_commit == "new_commit_sha"
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_sync_deletes_removed_files(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # old_file.py should be deleted
        cursor = await db.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ? AND path = ?",
            (repo_record.id, "src/old_file.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_sync_deletes_removed_symbols(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # old_func symbol should be deleted (cascaded via file delete)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo_id = ? AND name = ?",
            (repo_record.id, "old_func"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_sync_deletes_file_embeddings_for_removed(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        # Get the old file's ID before sync
        cursor = await db.execute(
            "SELECT id FROM files WHERE repo_id = ? AND path = ?",
            (repo_record.id, "src/old_file.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        old_file_id = row[0]

        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # File embedding for old_file should be removed
        cursor = await db.execute(
            "SELECT COUNT(*) FROM vec_file_embeddings WHERE file_id = ?",
            (old_file_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_sync_stores_added_files(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        cursor = await db.execute(
            "SELECT path FROM files WHERE repo_id = ? AND path = ?",
            (repo_record.id, "src/new_file.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "src/new_file.py"

    @pytest.mark.asyncio
    async def test_sync_updates_modified_files(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # main.py should be updated (lines_of_code from parser is 6)
        cursor = await db.execute(
            "SELECT lines_of_code FROM files WHERE repo_id = ? AND path = ?",
            (repo_record.id, "src/main.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 6

    @pytest.mark.asyncio
    async def test_sync_calls_llm_tier2(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        mock_llm: AsyncMock,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # Tier 2: one batch call for 2 changed files (added + modified)
        assert mock_llm.summarize_batch.call_count >= 1
        first_call = mock_llm.summarize_batch.call_args_list[0]
        prompts = first_call[0][0]
        assert len(prompts) == 2

    @pytest.mark.asyncio
    async def test_sync_calls_llm_tier3(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        mock_llm: AsyncMock,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # Tier 3: second batch call for function symbols
        assert mock_llm.summarize_batch.call_count >= 2
        second_call = mock_llm.summarize_batch.call_args_list[1]
        prompts = second_call[0][0]
        assert len(prompts) == 2  # main + new_func

    @pytest.mark.asyncio
    async def test_sync_generates_embeddings(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        mock_embedder: MagicMock,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        # embed() called per file and per symbol for changed files
        assert mock_embedder.embed.call_count >= 2  # at least 2 files

    @pytest.mark.asyncio
    async def test_sync_updates_indexed_commit(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        cursor = await db.execute(
            "SELECT indexed_commit, last_indexed_at FROM repositories WHERE id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "new_commit_sha"
        assert row[1] is not None

    @pytest.mark.asyncio
    async def test_sync_llm_calls_count(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        result = await syncer.sync(repo_record)

        # Tier 2: 2 files + Tier 3: 2 functions + Tier 1: 1 = 5
        assert result.llm_calls_made == 5

    @pytest.mark.asyncio
    async def test_sync_token_count(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        result = await syncer.sync(repo_record)

        # main.py: 20 tokens + new_file.py: 8 tokens = 28
        assert result.tokens_used == 28


# -- Tier 1 Rebuild -----------------------------------------------------------


class TestTier1Rebuild:
    @pytest.mark.asyncio
    async def test_tier1_rebuilt_when_ratio_exceeds_threshold(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        mock_llm: AsyncMock,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        result = await syncer.sync(repo_record)

        # 3 changed (1 added + 1 modified + 1 deleted) out of 2 total files = 1.5 ratio
        # which exceeds 0.10 threshold
        assert result.tier1_rebuilt is True
        assert mock_llm.summarize.call_count == 1  # Tier 1 call

    @pytest.mark.asyncio
    async def test_tier1_not_rebuilt_when_ratio_below_threshold(
        self,
        db: Database,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        repo_dir: Path,
        repo_id: int,
    ) -> None:
        # Create config with very high threshold
        config = Settings(
            data_dir=repo_dir.parent / "data",
            repos_dir=repo_dir.parent / "data" / "repos",
            db_path=repo_dir.parent / "test.db",
            tier1_rebuild_threshold=100.0,  # impossibly high
        )

        mock_git = AsyncMock(spec=GitOperations)
        mock_git.get_head_commit.return_value = "new_commit_sha"
        mock_git.diff_commits.return_value = DiffResult(
            added=[],
            modified=["src/main.py"],
            deleted=[],
            renamed=[],
        )

        # Pre-insert many files so the ratio is very low
        for i in range(100):
            await db.execute(
                "INSERT INTO files (repo_id, path, language, lines_of_code, token_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (repo_id, f"src/file_{i}.py", "python", 10, 50),
            )
        await db.conn.commit()

        repo_record = Repository(
            id=repo_id,
            name="my-repo",
            remote_url=None,
            local_path=str(repo_dir),
            default_branch="main",
            indexed_commit="old_commit_sha",
            last_indexed_at=None,
            created_at="2024-01-01T00:00:00",
        )

        syncer = Syncer(db, mock_git, mock_parser, mock_llm, mock_embedder, config)
        result = await syncer.sync(repo_record)

        assert result.tier1_rebuilt is False
        mock_llm.summarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier1_stores_overview(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        db: Database,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        await syncer.sync(repo_record)

        cursor = await db.execute(
            "SELECT overview, commit_sha FROM repo_overviews WHERE repo_id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "# Repository Overview\nThis is a test repo."
        assert row[1] == "new_commit_sha"


# -- Dry Run ------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_estimates(
        self,
        syncer: Syncer,
        repo_record: Repository,
    ) -> None:
        result = await syncer.sync(repo_record, dry_run=True)

        assert isinstance(result, SyncResult)
        assert result.already_current is False
        assert result.files_added == 1
        assert result.files_modified == 1
        assert result.files_deleted == 1

    @pytest.mark.asyncio
    async def test_dry_run_no_llm_calls(
        self,
        syncer: Syncer,
        repo_record: Repository,
        mock_llm: AsyncMock,
    ) -> None:
        await syncer.sync(repo_record, dry_run=True)
        mock_llm.summarize.assert_not_called()
        mock_llm.summarize_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(
        self,
        syncer: Syncer,
        repo_record: Repository,
        db: Database,
    ) -> None:
        await syncer.sync(repo_record, dry_run=True)

        # No new files should be stored
        cursor = await db.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ?",
            (repo_record.id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0  # no files stored

    @pytest.mark.asyncio
    async def test_dry_run_no_embeddings(
        self,
        syncer: Syncer,
        repo_record: Repository,
        mock_embedder: MagicMock,
    ) -> None:
        await syncer.sync(repo_record, dry_run=True)
        mock_embedder.embed.assert_not_called()
        mock_embedder.embed_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_estimates_llm_calls(
        self,
        syncer: Syncer,
        repo_record: Repository,
    ) -> None:
        result = await syncer.sync(repo_record, dry_run=True)
        # 2 changed files * 2 (Tier 2 + Tier 3) + 1 (Tier 1) = 5
        assert result.llm_calls_made == 5


# -- Path Filter ---------------------------------------------------------------


class TestPathFilter:
    @pytest.mark.asyncio
    async def test_path_filter_restricts_scope(
        self,
        syncer: Syncer,
        repo_record: Repository,
        indexed_repo: None,
        repo_dir: Path,
    ) -> None:
        (repo_dir / "src" / "new_file.py").write_text("def new_func():\n    pass\n")
        result = await syncer.sync(repo_record, path_filter="src/new")

        # Only the added file matches the filter
        assert result.files_added == 1
        assert result.files_modified == 0
        assert result.files_deleted == 0

    @pytest.mark.asyncio
    async def test_path_filter_no_match(
        self,
        syncer: Syncer,
        repo_record: Repository,
    ) -> None:
        result = await syncer.sync(repo_record, path_filter="nonexistent/")

        assert result.files_added == 0
        assert result.files_modified == 0
        assert result.files_deleted == 0


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
        git.get_head_commit.side_effect = RuntimeError("git broke")
        syncer = Syncer(db, git, mock_parser, mock_llm, mock_embedder, config)

        with pytest.raises(IndexError, match="Sync failed.*git broke"):
            await syncer.sync(repo_record)

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
        git.get_head_commit.side_effect = IndexError("already an IndexError")
        syncer = Syncer(db, git, mock_parser, mock_llm, mock_embedder, config)

        with pytest.raises(IndexError, match="already an IndexError"):
            await syncer.sync(repo_record)


# -- No Index (empty indexed_commit) ------------------------------------------


class TestNoIndex:
    @pytest.mark.asyncio
    async def test_sync_with_no_prior_index(
        self,
        db: Database,
        mock_git: AsyncMock,
        mock_parser: MagicMock,
        mock_llm: AsyncMock,
        mock_embedder: MagicMock,
        config: Settings,
        repo_dir: Path,
    ) -> None:
        """Sync with indexed_commit=None (never indexed before) still works."""
        cursor = await db.execute(
            "INSERT INTO repositories (name, local_path, default_branch) "
            "VALUES (?, ?, ?)",
            ("fresh-repo", str(repo_dir), "main"),
        )
        await db.conn.commit()
        assert cursor.lastrowid is not None

        repo = Repository(
            id=cursor.lastrowid,
            name="fresh-repo",
            remote_url=None,
            local_path=str(repo_dir),
            default_branch="main",
            indexed_commit=None,
            last_indexed_at=None,
            created_at="2024-01-01T00:00:00",
        )

        mock_git.diff_commits.return_value = DiffResult(
            added=["src/main.py"],
            modified=[],
            deleted=[],
            renamed=[],
        )

        syncer = Syncer(db, mock_git, mock_parser, mock_llm, mock_embedder, config)
        result = await syncer.sync(repo)

        assert result.already_current is False
        assert result.files_added == 1
        assert result.old_commit == ""


# -- SyncResult dataclass ----------------------------------------------------


class TestSyncResult:
    def test_fields(self) -> None:
        result = SyncResult(
            already_current=False,
            files_added=5,
            files_modified=3,
            files_deleted=1,
            llm_calls_made=12,
            tokens_used=3000,
            tier1_rebuilt=True,
            old_commit="abc123",
            new_commit="def456",
            duration_seconds=2.5,
        )
        assert result.already_current is False
        assert result.files_added == 5
        assert result.files_modified == 3
        assert result.files_deleted == 1
        assert result.llm_calls_made == 12
        assert result.tokens_used == 3000
        assert result.tier1_rebuilt is True
        assert result.old_commit == "abc123"
        assert result.new_commit == "def456"
        assert result.duration_seconds == 2.5
