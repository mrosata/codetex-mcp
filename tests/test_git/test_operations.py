"""Tests for git/operations.py — async subprocess git wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codetex_mcp.config.settings import Settings
from codetex_mcp.exceptions import GitAuthError, GitError
from codetex_mcp.git.operations import DiffResult, GitOperations


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / ".codetex")


@pytest.fixture
def git_ops(settings: Settings) -> GitOperations:
    return GitOperations(settings)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


class TestGetHeadCommit:
    @pytest.mark.asyncio
    async def test_returns_sha(self, git_ops: GitOperations, git_repo: Path) -> None:
        sha = await git_ops.get_head_commit(git_repo)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    @pytest.mark.asyncio
    async def test_matches_git_rev_parse(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        expected = result.stdout.strip()
        sha = await git_ops.get_head_commit(git_repo)
        assert sha == expected

    @pytest.mark.asyncio
    async def test_raises_on_non_git_dir(
        self, git_ops: GitOperations, tmp_path: Path
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        with pytest.raises(GitError):
            await git_ops.get_head_commit(non_repo)


class TestGetDefaultBranch:
    @pytest.mark.asyncio
    async def test_returns_branch_name(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        branch = await git_ops.get_default_branch(git_repo)
        # Modern git defaults to "main" or "master"
        assert branch in ("main", "master")

    @pytest.mark.asyncio
    async def test_returns_current_branch(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "develop"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        branch = await git_ops.get_default_branch(git_repo)
        assert branch == "develop"


class TestGetRemoteUrl:
    @pytest.mark.asyncio
    async def test_no_remote_returns_none(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        url = await git_ops.get_remote_url(git_repo)
        assert url is None

    @pytest.mark.asyncio
    async def test_returns_origin_url(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/repo.git"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        url = await git_ops.get_remote_url(git_repo)
        assert url == "https://github.com/user/repo.git"


class TestDiffCommits:
    @pytest.mark.asyncio
    async def test_added_file(self, git_ops: GitOperations, git_repo: Path) -> None:
        old_sha = await git_ops.get_head_commit(git_repo)
        (git_repo / "new_file.py").write_text("print('hello')\n")
        subprocess.run(
            ["git", "add", "."], cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add new file"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        new_sha = await git_ops.get_head_commit(git_repo)
        diff = await git_ops.diff_commits(git_repo, old_sha, new_sha)
        assert "new_file.py" in diff.added
        assert diff.modified == []
        assert diff.deleted == []

    @pytest.mark.asyncio
    async def test_modified_file(self, git_ops: GitOperations, git_repo: Path) -> None:
        old_sha = await git_ops.get_head_commit(git_repo)
        (git_repo / "README.md").write_text("# Updated\n")
        subprocess.run(
            ["git", "add", "."], cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Modify readme"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        new_sha = await git_ops.get_head_commit(git_repo)
        diff = await git_ops.diff_commits(git_repo, old_sha, new_sha)
        assert "README.md" in diff.modified

    @pytest.mark.asyncio
    async def test_deleted_file(self, git_ops: GitOperations, git_repo: Path) -> None:
        old_sha = await git_ops.get_head_commit(git_repo)
        subprocess.run(
            ["git", "rm", "README.md"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Delete readme"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        new_sha = await git_ops.get_head_commit(git_repo)
        diff = await git_ops.diff_commits(git_repo, old_sha, new_sha)
        assert "README.md" in diff.deleted

    @pytest.mark.asyncio
    async def test_renamed_file(self, git_ops: GitOperations, git_repo: Path) -> None:
        old_sha = await git_ops.get_head_commit(git_repo)
        subprocess.run(
            ["git", "mv", "README.md", "DOCS.md"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Rename readme"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        new_sha = await git_ops.get_head_commit(git_repo)
        diff = await git_ops.diff_commits(git_repo, old_sha, new_sha)
        assert any(old == "README.md" and new == "DOCS.md" for old, new in diff.renamed)

    @pytest.mark.asyncio
    async def test_empty_diff(self, git_ops: GitOperations, git_repo: Path) -> None:
        sha = await git_ops.get_head_commit(git_repo)
        diff = await git_ops.diff_commits(git_repo, sha, sha)
        assert diff.added == []
        assert diff.modified == []
        assert diff.deleted == []
        assert diff.renamed == []


class TestParseDiffOutput:
    def test_added(self) -> None:
        result = GitOperations._parse_diff_output("A\tsrc/main.py")
        assert result.added == ["src/main.py"]

    def test_modified(self) -> None:
        result = GitOperations._parse_diff_output("M\tsrc/main.py")
        assert result.modified == ["src/main.py"]

    def test_deleted(self) -> None:
        result = GitOperations._parse_diff_output("D\tsrc/main.py")
        assert result.deleted == ["src/main.py"]

    def test_renamed(self) -> None:
        result = GitOperations._parse_diff_output("R100\told.py\tnew.py")
        assert result.renamed == [("old.py", "new.py")]

    def test_mixed(self) -> None:
        output = "A\tadd.py\nM\tmod.py\nD\tdel.py\nR095\told.py\tnew.py"
        result = GitOperations._parse_diff_output(output)
        assert result.added == ["add.py"]
        assert result.modified == ["mod.py"]
        assert result.deleted == ["del.py"]
        assert result.renamed == [("old.py", "new.py")]

    def test_empty_output(self) -> None:
        result = GitOperations._parse_diff_output("")
        assert result == DiffResult()


class TestListTrackedFiles:
    @pytest.mark.asyncio
    async def test_lists_tracked_files(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        files = await git_ops.list_tracked_files(git_repo)
        assert "README.md" in files

    @pytest.mark.asyncio
    async def test_includes_new_tracked_files(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        (git_repo / "new.py").write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "new.py"], cwd=git_repo, check=True, capture_output=True
        )
        files = await git_ops.list_tracked_files(git_repo)
        assert "new.py" in files
        assert "README.md" in files

    @pytest.mark.asyncio
    async def test_excludes_untracked_files(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        (git_repo / "untracked.txt").write_text("not tracked\n")
        files = await git_ops.list_tracked_files(git_repo)
        assert "untracked.txt" not in files


class TestIsGitRepo:
    @pytest.mark.asyncio
    async def test_returns_true_for_git_repo(
        self, git_ops: GitOperations, git_repo: Path
    ) -> None:
        assert await git_ops.is_git_repo(git_repo) is True

    @pytest.mark.asyncio
    async def test_returns_false_for_non_repo(
        self, git_ops: GitOperations, tmp_path: Path
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        assert await git_ops.is_git_repo(non_repo) is False

    @pytest.mark.asyncio
    async def test_returns_false_for_nonexistent_path(
        self, git_ops: GitOperations, tmp_path: Path
    ) -> None:
        assert await git_ops.is_git_repo(tmp_path / "does-not-exist") is False


class TestClone:
    @pytest.mark.asyncio
    async def test_clone_local_repo(
        self, git_ops: GitOperations, git_repo: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "cloned"
        await git_ops.clone(str(git_repo), target)
        assert (target / "README.md").exists()
        assert await git_ops.is_git_repo(target)

    @pytest.mark.asyncio
    async def test_clone_invalid_url_raises_git_error(
        self, git_ops: GitOperations, tmp_path: Path
    ) -> None:
        target = tmp_path / "bad-clone"
        with pytest.raises(GitError):
            await git_ops.clone("https://invalid.example.com/no-repo.git", target)


class TestGitAuthError:
    def test_auth_error_detection(self) -> None:
        git_ops = GitOperations(Settings())
        with pytest.raises(GitAuthError, match="Authentication failed"):
            git_ops._raise_git_error(
                ("clone", "https://github.com/private/repo.git"),
                "fatal: Authentication failed for 'https://github.com/private/repo.git'",
            )

    def test_permission_denied_detection(self) -> None:
        git_ops = GitOperations(Settings())
        with pytest.raises(GitAuthError, match="Authentication failed"):
            git_ops._raise_git_error(
                ("clone", "git@github.com:private/repo.git"),
                "Permission denied (publickey)",
            )

    def test_non_auth_error_raises_git_error(self) -> None:
        git_ops = GitOperations(Settings())
        with pytest.raises(GitError, match="not found"):
            git_ops._raise_git_error(
                ("clone", "https://github.com/user/repo.git"),
                "fatal: repository not found",
            )
