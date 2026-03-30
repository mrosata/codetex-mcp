from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codetex_mcp.exceptions import RepositoryAlreadyExistsError
from codetex_mcp.storage.database import Database


@dataclass
class Repository:
    id: int
    name: str
    remote_url: str | None
    local_path: str
    default_branch: str
    indexed_commit: str | None
    last_indexed_at: str | None
    created_at: str


def _row_to_repo(row: Any) -> Repository:
    return Repository(
        id=int(row[0]),
        name=str(row[1]),
        remote_url=str(row[2]) if row[2] is not None else None,
        local_path=str(row[3]),
        default_branch=str(row[4]),
        indexed_commit=str(row[5]) if row[5] is not None else None,
        last_indexed_at=str(row[6]) if row[6] is not None else None,
        created_at=str(row[7]),
    )


async def create_repo(
    db: Database,
    name: str,
    remote_url: str | None,
    local_path: str,
    default_branch: str,
) -> Repository:
    try:
        cursor = await db.execute(
            "INSERT INTO repositories (name, remote_url, local_path, default_branch) "
            "VALUES (?, ?, ?, ?)",
            (name, remote_url, local_path, default_branch),
        )
        await db.conn.commit()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise RepositoryAlreadyExistsError(
                f"Repository '{name}' already exists"
            ) from exc
        raise

    repo_id = cursor.lastrowid
    assert repo_id is not None

    return await _get_repo_by_id(db, repo_id)


async def _get_repo_by_id(db: Database, repo_id: int) -> Repository:
    cursor = await db.execute(
        "SELECT id, name, remote_url, local_path, default_branch, "
        "indexed_commit, last_indexed_at, created_at "
        "FROM repositories WHERE id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    return _row_to_repo(row)


async def get_repo_by_name(db: Database, name: str) -> Repository | None:
    cursor = await db.execute(
        "SELECT id, name, remote_url, local_path, default_branch, "
        "indexed_commit, last_indexed_at, created_at "
        "FROM repositories WHERE name = ?",
        (name,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_repo(row)


async def list_repos(db: Database) -> list[Repository]:
    cursor = await db.execute(
        "SELECT id, name, remote_url, local_path, default_branch, "
        "indexed_commit, last_indexed_at, created_at "
        "FROM repositories ORDER BY name"
    )
    rows = await cursor.fetchall()
    return [_row_to_repo(row) for row in rows]


async def update_indexed_commit(db: Database, repo_id: int, commit_sha: str) -> None:
    await db.execute(
        "UPDATE repositories SET indexed_commit = ?, last_indexed_at = datetime('now') "
        "WHERE id = ?",
        (commit_sha, repo_id),
    )
    await db.conn.commit()


async def delete_repo(db: Database, repo_id: int) -> None:
    await db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    await db.conn.commit()
