from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from codetex_mcp.exceptions import RepositoryAlreadyExistsError
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import (
    Repository,
    create_repo,
    delete_repo,
    get_repo_by_name,
    list_repos,
    update_indexed_commit,
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


class TestCreateRepo:
    @pytest.mark.asyncio
    async def test_create_repo_returns_repository(self, db: Database) -> None:
        repo = await create_repo(db, "my-repo", "https://github.com/user/my-repo.git", "/tmp/repos/my-repo", "main")
        assert isinstance(repo, Repository)
        assert repo.name == "my-repo"
        assert repo.remote_url == "https://github.com/user/my-repo.git"
        assert repo.local_path == "/tmp/repos/my-repo"
        assert repo.default_branch == "main"
        assert repo.indexed_commit is None
        assert repo.last_indexed_at is None
        assert repo.created_at is not None
        assert repo.id > 0

    @pytest.mark.asyncio
    async def test_create_repo_without_remote_url(self, db: Database) -> None:
        repo = await create_repo(db, "local-repo", None, "/home/user/project", "master")
        assert repo.name == "local-repo"
        assert repo.remote_url is None
        assert repo.local_path == "/home/user/project"
        assert repo.default_branch == "master"

    @pytest.mark.asyncio
    async def test_create_repo_duplicate_name_raises(self, db: Database) -> None:
        await create_repo(db, "dup-repo", None, "/tmp/a", "main")
        with pytest.raises(RepositoryAlreadyExistsError, match="dup-repo"):
            await create_repo(db, "dup-repo", None, "/tmp/b", "main")


class TestGetRepoByName:
    @pytest.mark.asyncio
    async def test_get_existing_repo(self, db: Database) -> None:
        created = await create_repo(db, "find-me", "https://example.com/find-me.git", "/tmp/find-me", "main")
        found = await get_repo_by_name(db, "find-me")
        assert found is not None
        assert found.id == created.id
        assert found.name == "find-me"
        assert found.remote_url == "https://example.com/find-me.git"

    @pytest.mark.asyncio
    async def test_get_nonexistent_repo_returns_none(self, db: Database) -> None:
        result = await get_repo_by_name(db, "no-such-repo")
        assert result is None


class TestListRepos:
    @pytest.mark.asyncio
    async def test_list_empty(self, db: Database) -> None:
        repos = await list_repos(db)
        assert repos == []

    @pytest.mark.asyncio
    async def test_list_multiple_repos(self, db: Database) -> None:
        await create_repo(db, "beta-repo", None, "/tmp/beta", "main")
        await create_repo(db, "alpha-repo", None, "/tmp/alpha", "main")
        repos = await list_repos(db)
        assert len(repos) == 2
        # Ordered by name
        assert repos[0].name == "alpha-repo"
        assert repos[1].name == "beta-repo"


class TestUpdateIndexedCommit:
    @pytest.mark.asyncio
    async def test_update_sets_commit_and_timestamp(self, db: Database) -> None:
        repo = await create_repo(db, "idx-repo", None, "/tmp/idx", "main")
        assert repo.indexed_commit is None
        assert repo.last_indexed_at is None

        await update_indexed_commit(db, repo.id, "abc123def456")

        updated = await get_repo_by_name(db, "idx-repo")
        assert updated is not None
        assert updated.indexed_commit == "abc123def456"
        assert updated.last_indexed_at is not None

    @pytest.mark.asyncio
    async def test_update_overwrites_previous_commit(self, db: Database) -> None:
        repo = await create_repo(db, "overwrite-repo", None, "/tmp/ow", "main")
        await update_indexed_commit(db, repo.id, "first_sha")
        await update_indexed_commit(db, repo.id, "second_sha")

        updated = await get_repo_by_name(db, "overwrite-repo")
        assert updated is not None
        assert updated.indexed_commit == "second_sha"


class TestDeleteRepo:
    @pytest.mark.asyncio
    async def test_delete_removes_repo(self, db: Database) -> None:
        repo = await create_repo(db, "del-repo", None, "/tmp/del", "main")
        await delete_repo(db, repo.id)
        result = await get_repo_by_name(db, "del-repo")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self, db: Database) -> None:
        await delete_repo(db, 9999)  # should not raise
