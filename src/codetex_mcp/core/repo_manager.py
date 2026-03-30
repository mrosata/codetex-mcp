"""RepoManager — repository lifecycle: clone, register, list, get, remove."""

from __future__ import annotations

from pathlib import Path

from codetex_mcp.config.settings import Settings
from codetex_mcp.exceptions import (
    GitError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.repositories import (
    Repository,
    create_repo,
    delete_repo,
    get_repo_by_name,
    list_repos,
)


def _is_remote_url(target: str) -> bool:
    """Return True if target looks like a remote URL rather than a local path."""
    return "://" in target or target.startswith("git@")


def _repo_name_from_url(url: str) -> str:
    """Derive a repo name from a remote URL.

    Strips trailing .git suffix and takes the basename.
    Examples:
        https://github.com/user/my-repo.git  → my-repo
        git@github.com:user/my-repo.git      → my-repo
        https://github.com/user/my-repo      → my-repo
    """
    # Handle trailing slashes
    url = url.rstrip("/")
    # Get the last path component
    basename = url.rsplit("/", 1)[-1]
    # Also handle git@ SSH URLs with colon separator
    basename = basename.rsplit(":", 1)[-1]
    # Strip .git suffix
    if basename.endswith(".git"):
        basename = basename[:-4]
    return basename


class RepoManager:
    """Manages repository lifecycle: clone, register local, list, get, remove."""

    def __init__(self, db: Database, git: GitOperations, config: Settings) -> None:
        self._db = db
        self._git = git
        self._config = config

    async def add_remote(self, url: str) -> Repository:
        """Clone a remote repository and register it in the database.

        Raises RepositoryAlreadyExistsError if a repo with the same name exists.
        Raises GitAuthError on authentication failure.
        Raises GitError on other clone failures.
        """
        name = _repo_name_from_url(url)

        # Check for duplicate before cloning
        existing = await get_repo_by_name(self._db, name)
        if existing is not None:
            raise RepositoryAlreadyExistsError(f"Repository '{name}' already exists")

        assert self._config.repos_dir is not None
        target_dir = self._config.repos_dir / name
        await self._git.clone(url, target_dir)

        default_branch = await self._git.get_default_branch(target_dir)
        return await create_repo(self._db, name, url, str(target_dir), default_branch)

    async def add_local(self, path: Path) -> Repository:
        """Register an existing local git repository.

        Raises GitError if path is not a git repository.
        Raises RepositoryAlreadyExistsError if a repo with the same name exists.
        """
        path = path.resolve()

        if not await self._git.is_git_repo(path):
            raise GitError(f"'{path}' is not a git repository")

        name = path.name

        existing = await get_repo_by_name(self._db, name)
        if existing is not None:
            raise RepositoryAlreadyExistsError(f"Repository '{name}' already exists")

        remote_url = await self._git.get_remote_url(path)
        default_branch = await self._git.get_default_branch(path)
        return await create_repo(self._db, name, remote_url, str(path), default_branch)

    async def list_repos(self) -> list[Repository]:
        """Return all registered repositories."""
        return await list_repos(self._db)

    async def get_repo(self, name: str) -> Repository:
        """Return a repository by name.

        Raises RepositoryNotFoundError if not found.
        """
        repo = await get_repo_by_name(self._db, name)
        if repo is None:
            raise RepositoryNotFoundError(f"Repository '{name}' not found")
        return repo

    async def remove_repo(self, name: str) -> None:
        """Remove a repository from the database (does not delete cloned files).

        Raises RepositoryNotFoundError if not found.
        """
        repo = await self.get_repo(name)
        await delete_repo(self._db, repo.id)
