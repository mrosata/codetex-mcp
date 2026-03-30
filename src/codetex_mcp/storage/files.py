from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codetex_mcp.storage.database import Database


@dataclass
class FileRecord:
    id: int
    repo_id: int
    path: str
    language: str | None
    lines_of_code: int
    token_count: int
    role: str | None
    summary: str | None
    imports_json: str | None
    updated_at: str


def _row_to_file(row: Any) -> FileRecord:
    return FileRecord(
        id=int(row[0]),
        repo_id=int(row[1]),
        path=str(row[2]),
        language=str(row[3]) if row[3] is not None else None,
        lines_of_code=int(row[4]),
        token_count=int(row[5]),
        role=str(row[6]) if row[6] is not None else None,
        summary=str(row[7]) if row[7] is not None else None,
        imports_json=str(row[8]) if row[8] is not None else None,
        updated_at=str(row[9]),
    )


async def upsert_file(
    db: Database,
    repo_id: int,
    path: str,
    language: str | None,
    lines_of_code: int,
    token_count: int,
    imports_json: str | None,
) -> int:
    cursor = await db.execute(
        "INSERT INTO files (repo_id, path, language, lines_of_code, token_count, imports_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(repo_id, path) DO UPDATE SET "
        "language = excluded.language, "
        "lines_of_code = excluded.lines_of_code, "
        "token_count = excluded.token_count, "
        "imports_json = excluded.imports_json, "
        "updated_at = datetime('now')",
        (repo_id, path, language, lines_of_code, token_count, imports_json),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def update_file_summary(
    db: Database, file_id: int, summary: str, role: str
) -> None:
    await db.execute(
        "UPDATE files SET summary = ?, role = ?, updated_at = datetime('now') WHERE id = ?",
        (summary, role, file_id),
    )
    await db.conn.commit()


async def get_file(db: Database, repo_id: int, path: str) -> FileRecord | None:
    cursor = await db.execute(
        "SELECT id, repo_id, path, language, lines_of_code, token_count, "
        "role, summary, imports_json, updated_at "
        "FROM files WHERE repo_id = ? AND path = ?",
        (repo_id, path),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_file(row)


async def list_files(db: Database, repo_id: int) -> list[FileRecord]:
    cursor = await db.execute(
        "SELECT id, repo_id, path, language, lines_of_code, token_count, "
        "role, summary, imports_json, updated_at "
        "FROM files WHERE repo_id = ? ORDER BY path",
        (repo_id,),
    )
    rows = await cursor.fetchall()
    return [_row_to_file(row) for row in rows]


async def delete_file(db: Database, file_id: int) -> None:
    await db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    await db.conn.commit()


async def count_files(db: Database, repo_id: int) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM files WHERE repo_id = ?", (repo_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


async def get_total_tokens(db: Database, repo_id: int) -> int:
    cursor = await db.execute(
        "SELECT COALESCE(SUM(token_count), 0) FROM files WHERE repo_id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


async def upsert_dependency(
    db: Database,
    repo_id: int,
    source_file_id: int,
    target_path: str,
    imported_names_json: str | None,
) -> None:
    await db.execute(
        "INSERT INTO dependencies (repo_id, source_file_id, target_path, imported_names) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(source_file_id, target_path) DO UPDATE SET "
        "imported_names = excluded.imported_names",
        (repo_id, source_file_id, target_path, imported_names_json),
    )
    await db.conn.commit()


async def delete_dependencies_by_file(db: Database, file_id: int) -> None:
    await db.execute("DELETE FROM dependencies WHERE source_file_id = ?", (file_id,))
    await db.conn.commit()
