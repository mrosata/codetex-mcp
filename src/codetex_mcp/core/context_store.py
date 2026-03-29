"""ContextStore — reads indexed context from the database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codetex_mcp.storage.database import Database


@dataclass
class FileContext:
    summary: str | None
    role: str | None
    imports: str | None
    symbols: list[SymbolBrief]
    lines_of_code: int
    token_count: int


@dataclass
class SymbolBrief:
    name: str
    kind: str
    signature: str
    start_line: int
    end_line: int


@dataclass
class SymbolDetail:
    signature: str
    summary: str | None
    parameters: str | None
    return_type: str | None
    calls: str | None
    file_path: str
    start_line: int


@dataclass
class RepoStatus:
    indexed_commit: str | None
    files_indexed: int
    symbols_indexed: int
    total_tokens: int
    last_indexed_at: str | None


class ContextStore:
    """Reads indexed context from the database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_repo_overview(self, repo_id: int) -> str | None:
        """Return the Tier 1 overview string for a repo, or None if not indexed."""
        cursor = await self._db.execute(
            "SELECT overview FROM repo_overviews WHERE repo_id = ?",
            (repo_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])

    async def get_file_context(
        self, repo_id: int, file_path: str
    ) -> FileContext | None:
        """Return Tier 2 file context, or None if the file is not indexed."""
        cursor = await self._db.execute(
            "SELECT id, summary, role, imports_json, lines_of_code, token_count "
            "FROM files WHERE repo_id = ? AND path = ?",
            (repo_id, file_path),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        file_id = int(row[0])
        symbols = await self._get_symbols_brief(file_id)

        return FileContext(
            summary=_str_or_none(row[1]),
            role=_str_or_none(row[2]),
            imports=_str_or_none(row[3]),
            symbols=symbols,
            lines_of_code=int(row[4]),
            token_count=int(row[5]),
        )

    async def get_symbol_detail(
        self, repo_id: int, symbol_name: str
    ) -> SymbolDetail | None:
        """Return Tier 3 symbol detail, or None if the symbol is not found."""
        cursor = await self._db.execute(
            "SELECT s.signature, s.summary, s.parameters_json, s.return_type, "
            "s.calls_json, f.path, s.start_line "
            "FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.repo_id = ? AND s.name = ?",
            (repo_id, symbol_name),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return SymbolDetail(
            signature=str(row[0]),
            summary=_str_or_none(row[1]),
            parameters=_str_or_none(row[2]),
            return_type=_str_or_none(row[3]),
            calls=_str_or_none(row[4]),
            file_path=str(row[5]),
            start_line=int(row[6]),
        )

    async def get_repo_status(self, repo_id: int) -> RepoStatus:
        """Return index status for a repository."""
        # Get repo metadata
        cursor = await self._db.execute(
            "SELECT indexed_commit, last_indexed_at "
            "FROM repositories WHERE id = ?",
            (repo_id,),
        )
        row = await cursor.fetchone()
        indexed_commit: str | None = None
        last_indexed_at: str | None = None
        if row is not None:
            indexed_commit = _str_or_none(row[0])
            last_indexed_at = _str_or_none(row[1])

        # Count files
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ?", (repo_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        files_indexed = int(row[0])

        # Count symbols
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo_id = ?", (repo_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        symbols_indexed = int(row[0])

        # Total tokens
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(token_count), 0) FROM files WHERE repo_id = ?",
            (repo_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        total_tokens = int(row[0])

        return RepoStatus(
            indexed_commit=indexed_commit,
            files_indexed=files_indexed,
            symbols_indexed=symbols_indexed,
            total_tokens=total_tokens,
            last_indexed_at=last_indexed_at,
        )

    async def _get_symbols_brief(self, file_id: int) -> list[SymbolBrief]:
        """Get brief symbol info for all symbols in a file."""
        cursor = await self._db.execute(
            "SELECT name, kind, signature, start_line, end_line "
            "FROM symbols WHERE file_id = ? ORDER BY start_line",
            (file_id,),
        )
        rows = await cursor.fetchall()
        return [
            SymbolBrief(
                name=str(row[0]),
                kind=str(row[1]),
                signature=str(row[2]),
                start_line=int(row[3]),
                end_line=int(row[4]),
            )
            for row in rows
        ]


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
