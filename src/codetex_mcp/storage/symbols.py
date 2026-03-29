from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codetex_mcp.storage.database import Database


@dataclass
class SymbolRecord:
    id: int
    file_id: int
    repo_id: int
    name: str
    kind: str
    signature: str
    docstring: str | None
    summary: str | None
    start_line: int
    end_line: int
    parameters_json: str | None
    return_type: str | None
    calls_json: str | None
    updated_at: str


def _row_to_symbol(row: Any) -> SymbolRecord:
    return SymbolRecord(
        id=int(row[0]),
        file_id=int(row[1]),
        repo_id=int(row[2]),
        name=str(row[3]),
        kind=str(row[4]),
        signature=str(row[5]),
        docstring=str(row[6]) if row[6] is not None else None,
        summary=str(row[7]) if row[7] is not None else None,
        start_line=int(row[8]),
        end_line=int(row[9]),
        parameters_json=str(row[10]) if row[10] is not None else None,
        return_type=str(row[11]) if row[11] is not None else None,
        calls_json=str(row[12]) if row[12] is not None else None,
        updated_at=str(row[13]),
    )


_SYMBOL_COLUMNS = (
    "id, file_id, repo_id, name, kind, signature, docstring, summary, "
    "start_line, end_line, parameters_json, return_type, calls_json, updated_at"
)


async def upsert_symbol(
    db: Database,
    file_id: int,
    repo_id: int,
    name: str,
    kind: str,
    signature: str,
    docstring: str | None,
    start_line: int,
    end_line: int,
    parameters_json: str | None,
    return_type: str | None,
    calls_json: str | None,
) -> int:
    cursor = await db.execute(
        "INSERT INTO symbols "
        "(file_id, repo_id, name, kind, signature, docstring, start_line, end_line, "
        "parameters_json, return_type, calls_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (file_id, repo_id, name, kind, signature, docstring, start_line, end_line,
         parameters_json, return_type, calls_json),
    )
    await db.conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def update_symbol_summary(
    db: Database, symbol_id: int, summary: str
) -> None:
    await db.execute(
        "UPDATE symbols SET summary = ?, updated_at = datetime('now') WHERE id = ?",
        (summary, symbol_id),
    )
    await db.conn.commit()


async def get_symbol(
    db: Database, repo_id: int, name: str
) -> SymbolRecord | None:
    cursor = await db.execute(
        f"SELECT {_SYMBOL_COLUMNS} FROM symbols WHERE repo_id = ? AND name = ?",
        (repo_id, name),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_symbol(row)


async def list_symbols_by_file(
    db: Database, file_id: int
) -> list[SymbolRecord]:
    cursor = await db.execute(
        f"SELECT {_SYMBOL_COLUMNS} FROM symbols WHERE file_id = ? ORDER BY start_line",
        (file_id,),
    )
    rows = await cursor.fetchall()
    return [_row_to_symbol(row) for row in rows]


async def delete_symbols_by_file(db: Database, file_id: int) -> None:
    await db.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    await db.conn.commit()
