from __future__ import annotations

import struct

from codetex_mcp.storage.database import Database


def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a list of floats into compact raw bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


async def upsert_file_embedding(
    db: Database, file_id: int, embedding: list[float]
) -> None:
    """Insert or replace a file embedding in the vec_file_embeddings table."""
    # vec0 virtual tables don't support ON CONFLICT, so delete first then insert.
    await db.execute(
        "DELETE FROM vec_file_embeddings WHERE file_id = ?", (file_id,)
    )
    await db.execute(
        "INSERT INTO vec_file_embeddings(file_id, embedding) VALUES (?, ?)",
        (file_id, _serialize_f32(embedding)),
    )
    await db.conn.commit()


async def upsert_symbol_embedding(
    db: Database, symbol_id: int, embedding: list[float]
) -> None:
    """Insert or replace a symbol embedding in the vec_symbol_embeddings table."""
    # vec0 virtual tables don't support ON CONFLICT, so delete first then insert.
    await db.execute(
        "DELETE FROM vec_symbol_embeddings WHERE symbol_id = ?", (symbol_id,)
    )
    await db.execute(
        "INSERT INTO vec_symbol_embeddings(symbol_id, embedding) VALUES (?, ?)",
        (symbol_id, _serialize_f32(embedding)),
    )
    await db.conn.commit()


async def delete_file_embedding(db: Database, file_id: int) -> None:
    """Delete a file embedding by file_id."""
    await db.execute(
        "DELETE FROM vec_file_embeddings WHERE file_id = ?", (file_id,)
    )
    await db.conn.commit()


async def delete_symbol_embedding(db: Database, symbol_id: int) -> None:
    """Delete a symbol embedding by symbol_id."""
    await db.execute(
        "DELETE FROM vec_symbol_embeddings WHERE symbol_id = ?", (symbol_id,)
    )
    await db.conn.commit()


async def search_file_embeddings(
    db: Database, query_embedding: list[float], limit: int = 10
) -> list[tuple[int, float]]:
    """Search for nearest file embeddings by cosine distance.

    Returns a list of (file_id, distance) tuples ordered by distance (ascending).
    """
    cursor = await db.execute(
        "SELECT file_id, distance "
        "FROM vec_file_embeddings "
        "WHERE embedding MATCH ? "
        "ORDER BY distance "
        "LIMIT ?",
        (_serialize_f32(query_embedding), limit),
    )
    rows = await cursor.fetchall()
    return [(int(row[0]), float(row[1])) for row in rows]


async def search_symbol_embeddings(
    db: Database, query_embedding: list[float], limit: int = 10
) -> list[tuple[int, float]]:
    """Search for nearest symbol embeddings by cosine distance.

    Returns a list of (symbol_id, distance) tuples ordered by distance (ascending).
    """
    cursor = await db.execute(
        "SELECT symbol_id, distance "
        "FROM vec_symbol_embeddings "
        "WHERE embedding MATCH ? "
        "ORDER BY distance "
        "LIMIT ?",
        (_serialize_f32(query_embedding), limit),
    )
    rows = await cursor.fetchall()
    return [(int(row[0]), float(row[1])) for row in rows]
