from __future__ import annotations

from pathlib import Path

import aiosqlite
import sqlite_vec  # type: ignore[import-untyped]

from codetex_mcp.exceptions import DatabaseError

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open connection, enable WAL mode, load sqlite-vec, enable foreign keys."""
        try:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.enable_load_extension(True)
            await self._conn.load_extension(sqlite_vec.loadable_path())
            await self._conn.enable_load_extension(False)
        except Exception as exc:
            raise DatabaseError(f"Failed to open database: {exc}") from exc

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise DatabaseError("Database not connected. Call connect() first.")
        return self._conn

    async def execute(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> aiosqlite.Cursor:
        """Execute a single SQL statement."""
        return await self.conn.execute(sql, params)

    async def executemany(
        self, sql: str, params_list: list[tuple[object, ...]]
    ) -> None:
        """Execute a SQL statement for each set of parameters."""
        await self.conn.executemany(sql, params_list)

    async def migrate(self) -> None:
        """Apply unapplied SQL migrations from the migrations directory."""
        conn = self.conn
        # Ensure schema_version table exists
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "    version INTEGER PRIMARY KEY,"
            "    applied TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        await conn.commit()

        # Find current version
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        current_version = row[0] if row else 0

        # Discover migration files sorted by numeric prefix
        migration_files = sorted(
            _MIGRATIONS_DIR.glob("*.sql"),
            key=lambda p: int(p.stem.split("_")[0]),
        )

        for migration_path in migration_files:
            version = int(migration_path.stem.split("_")[0])
            if version <= current_version:
                continue

            sql = migration_path.read_text()
            try:
                await conn.executescript(sql)
                await conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
                await conn.commit()
            except Exception as exc:
                raise DatabaseError(
                    f"Migration {migration_path.name} failed: {exc}"
                ) from exc
