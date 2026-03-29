from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from codetex_mcp.config.settings import Settings
from codetex_mcp.core.repo_manager import (
    RepoManager,
    _is_remote_url,
    _repo_name_from_url,
)
from codetex_mcp.exceptions import (
    GitError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import Repository


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
def mock_git() -> AsyncMock:
    git = AsyncMock(spec=GitOperations)
    git.is_git_repo.return_value = True
    git.get_default_branch.return_value = "main"
    git.get_remote_url.return_value = None
    return git


@pytest.fixture
def repo_manager(db: Database, mock_git: AsyncMock, config: Settings) -> RepoManager:
    return RepoManager(db, mock_git, config)


# ---------- URL detection ----------


class TestIsRemoteUrl:
    def test_https_url(self) -> None:
        assert _is_remote_url("https://github.com/user/repo.git") is True

    def test_ssh_url(self) -> None:
        assert _is_remote_url("git@github.com:user/repo.git") is True

    def test_git_protocol(self) -> None:
        assert _is_remote_url("git://example.com/repo.git") is True

    def test_local_absolute_path(self) -> None:
        assert _is_remote_url("/home/user/project") is False

    def test_local_relative_path(self) -> None:
        assert _is_remote_url("./my-project") is False

    def test_local_name_only(self) -> None:
        assert _is_remote_url("my-project") is False


# ---------- Name derivation ----------


class TestRepoNameFromUrl:
    def test_https_with_git_suffix(self) -> None:
        assert _repo_name_from_url("https://github.com/user/my-repo.git") == "my-repo"

    def test_https_without_git_suffix(self) -> None:
        assert _repo_name_from_url("https://github.com/user/my-repo") == "my-repo"

    def test_ssh_url(self) -> None:
        assert _repo_name_from_url("git@github.com:user/my-repo.git") == "my-repo"

    def test_trailing_slash(self) -> None:
        assert _repo_name_from_url("https://github.com/user/my-repo/") == "my-repo"


# ---------- add_remote ----------


class TestAddRemote:
    @pytest.mark.asyncio
    async def test_clone_and_register(
        self, repo_manager: RepoManager, mock_git: AsyncMock, config: Settings
    ) -> None:
        repo = await repo_manager.add_remote("https://github.com/user/my-repo.git")

        assert isinstance(repo, Repository)
        assert repo.name == "my-repo"
        assert repo.remote_url == "https://github.com/user/my-repo.git"
        assert config.repos_dir is not None
        assert repo.local_path == str(config.repos_dir / "my-repo")
        assert repo.default_branch == "main"

        mock_git.clone.assert_awaited_once_with(
            "https://github.com/user/my-repo.git",
            config.repos_dir / "my-repo",
        )
        mock_git.get_default_branch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_name_raises(self, repo_manager: RepoManager) -> None:
        await repo_manager.add_remote("https://github.com/user/dup-repo.git")
        with pytest.raises(RepositoryAlreadyExistsError, match="dup-repo"):
            await repo_manager.add_remote("https://github.com/other/dup-repo.git")

    @pytest.mark.asyncio
    async def test_clone_failure_propagates(
        self, repo_manager: RepoManager, mock_git: AsyncMock
    ) -> None:
        mock_git.clone.side_effect = GitError("clone failed: network error")
        with pytest.raises(GitError, match="network error"):
            await repo_manager.add_remote("https://github.com/user/fail.git")


# ---------- add_local ----------


class TestAddLocal:
    @pytest.mark.asyncio
    async def test_register_local_repo(
        self, repo_manager: RepoManager, tmp_path: Path, mock_git: AsyncMock
    ) -> None:
        local_path = tmp_path / "my-project"
        local_path.mkdir()
        mock_git.get_remote_url.return_value = "https://github.com/user/my-project.git"

        repo = await repo_manager.add_local(local_path)

        assert isinstance(repo, Repository)
        assert repo.name == "my-project"
        assert repo.remote_url == "https://github.com/user/my-project.git"
        assert repo.local_path == str(local_path.resolve())
        assert repo.default_branch == "main"

        mock_git.is_git_repo.assert_awaited_once_with(local_path.resolve())

    @pytest.mark.asyncio
    async def test_local_without_remote(
        self, repo_manager: RepoManager, tmp_path: Path
    ) -> None:
        local_path = tmp_path / "local-only"
        local_path.mkdir()

        repo = await repo_manager.add_local(local_path)

        assert repo.remote_url is None

    @pytest.mark.asyncio
    async def test_not_a_git_repo_raises(
        self, repo_manager: RepoManager, tmp_path: Path, mock_git: AsyncMock
    ) -> None:
        mock_git.is_git_repo.return_value = False
        with pytest.raises(GitError, match="not a git repository"):
            await repo_manager.add_local(tmp_path / "not-a-repo")

    @pytest.mark.asyncio
    async def test_duplicate_local_raises(
        self, repo_manager: RepoManager, tmp_path: Path
    ) -> None:
        local_path = tmp_path / "same-name"
        local_path.mkdir()
        await repo_manager.add_local(local_path)
        with pytest.raises(RepositoryAlreadyExistsError, match="same-name"):
            await repo_manager.add_local(local_path)


# ---------- list_repos ----------


class TestListRepos:
    @pytest.mark.asyncio
    async def test_empty_list(self, repo_manager: RepoManager) -> None:
        repos = await repo_manager.list_repos()
        assert repos == []

    @pytest.mark.asyncio
    async def test_list_after_adding(self, repo_manager: RepoManager, tmp_path: Path) -> None:
        path_a = tmp_path / "alpha"
        path_a.mkdir()
        path_b = tmp_path / "beta"
        path_b.mkdir()
        await repo_manager.add_local(path_a)
        await repo_manager.add_local(path_b)

        repos = await repo_manager.list_repos()
        assert len(repos) == 2
        names = [r.name for r in repos]
        assert "alpha" in names
        assert "beta" in names


# ---------- get_repo ----------


class TestGetRepo:
    @pytest.mark.asyncio
    async def test_get_existing(self, repo_manager: RepoManager, tmp_path: Path) -> None:
        local_path = tmp_path / "findable"
        local_path.mkdir()
        await repo_manager.add_local(local_path)

        repo = await repo_manager.get_repo("findable")
        assert repo.name == "findable"

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self, repo_manager: RepoManager) -> None:
        with pytest.raises(RepositoryNotFoundError, match="no-such-repo"):
            await repo_manager.get_repo("no-such-repo")


# ---------- remove_repo ----------


class TestRemoveRepo:
    @pytest.mark.asyncio
    async def test_remove_existing(self, repo_manager: RepoManager, tmp_path: Path) -> None:
        local_path = tmp_path / "removable"
        local_path.mkdir()
        await repo_manager.add_local(local_path)

        await repo_manager.remove_repo("removable")

        with pytest.raises(RepositoryNotFoundError):
            await repo_manager.get_repo("removable")

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises(self, repo_manager: RepoManager) -> None:
        with pytest.raises(RepositoryNotFoundError, match="ghost"):
            await repo_manager.remove_repo("ghost")
