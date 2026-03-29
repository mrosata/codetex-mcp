"""Async subprocess git wrapper — no gitpython dependency."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from codetex_mcp.config.settings import Settings
from codetex_mcp.exceptions import GitAuthError, GitError


@dataclass
class DiffResult:
    """Result of comparing two commits."""

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)


class GitOperations:
    """Async wrapper around the git binary using subprocess."""

    def __init__(self, config: Settings) -> None:
        self._config = config

    async def _run(
        self, *args: str, cwd: Path | None = None
    ) -> tuple[str, str]:
        """Run a git command and return (stdout, stderr).

        Raises GitError on non-zero exit code.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            self._raise_git_error(args, stderr)

        return stdout, stderr

    def _raise_git_error(self, args: tuple[str, ...], stderr: str) -> None:
        """Raise GitAuthError or GitError based on stderr content."""
        # Check for auth failures
        if args and args[0] == "clone":
            url = args[-1] if len(args) >= 2 else ""
            auth_markers = ("Permission denied", "Authentication failed")
            if any(marker in stderr for marker in auth_markers):
                raise GitAuthError(url)

        raise GitError(f"git {' '.join(args)} failed: {stderr}")

    async def clone(self, url: str, target_dir: Path) -> None:
        """Clone a repository to the target directory."""
        try:
            await self._run("clone", url, str(target_dir))
        except GitError:
            raise
        except Exception as e:
            raise GitError(f"Failed to clone '{url}': {e}") from e

    async def get_head_commit(self, repo_path: Path) -> str:
        """Return the current HEAD commit SHA."""
        stdout, _ = await self._run("rev-parse", "HEAD", cwd=repo_path)
        return stdout

    async def get_default_branch(self, repo_path: Path) -> str:
        """Return the default branch name."""
        # Try symbolic-ref for the current branch first
        try:
            stdout, _ = await self._run(
                "symbolic-ref", "--short", "HEAD", cwd=repo_path
            )
            return stdout
        except GitError:
            # Detached HEAD — fall back to checking remote HEAD
            pass

        try:
            stdout, _ = await self._run(
                "rev-parse", "--abbrev-ref", "origin/HEAD", cwd=repo_path
            )
            # Returns something like "origin/main" — strip the remote prefix
            if "/" in stdout:
                return stdout.split("/", 1)[1]
            return stdout
        except GitError:
            return "main"

    async def get_remote_url(self, repo_path: Path) -> str | None:
        """Return the origin remote URL, or None if no remote."""
        try:
            stdout, _ = await self._run(
                "remote", "get-url", "origin", cwd=repo_path
            )
            return stdout if stdout else None
        except GitError:
            return None

    async def diff_commits(
        self, repo_path: Path, from_sha: str, to_sha: str
    ) -> DiffResult:
        """Compute diff between two commits, returning categorized file changes."""
        stdout, _ = await self._run(
            "diff", "--name-status", f"{from_sha}..{to_sha}", cwd=repo_path
        )
        return self._parse_diff_output(stdout)

    @staticmethod
    def _parse_diff_output(output: str) -> DiffResult:
        """Parse git diff --name-status output into a DiffResult."""
        result = DiffResult()
        if not output:
            return result

        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue

            status = parts[0]
            if status == "A":
                result.added.append(parts[1])
            elif status == "M":
                result.modified.append(parts[1])
            elif status == "D":
                result.deleted.append(parts[1])
            elif status.startswith("R"):
                # Rename: R<score>\told_path\tnew_path
                if len(parts) >= 3:
                    result.renamed.append((parts[1], parts[2]))

        return result

    async def list_tracked_files(self, repo_path: Path) -> list[str]:
        """Return a list of all tracked file paths."""
        stdout, _ = await self._run("ls-files", cwd=repo_path)
        if not stdout:
            return []
        return stdout.splitlines()

    async def is_git_repo(self, path: Path) -> bool:
        """Check if the given path is inside a git repository."""
        try:
            await self._run(
                "rev-parse", "--is-inside-work-tree", cwd=path
            )
            return True
        except (GitError, FileNotFoundError):
            return False
