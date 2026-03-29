"""SearchEngine — semantic similarity search over indexed context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.vectors import search_file_embeddings, search_symbol_embeddings


@dataclass
class SearchResult:
    kind: Literal["file", "symbol"]
    path: str
    name: str
    summary: str
    score: float


class SearchEngine:
    """Performs semantic similarity search over indexed file and symbol embeddings."""

    def __init__(self, db: Database, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder

    async def search(
        self,
        repo_id: int,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search for files and symbols matching the query.

        Embeds the query, searches both vec_file_embeddings and
        vec_symbol_embeddings, merges and ranks by distance (ascending),
        and returns the top-N results.
        """
        query_embedding = self._embedder.embed(query)

        # Search both embedding tables
        file_hits = await search_file_embeddings(
            self._db, query_embedding, max_results
        )
        symbol_hits = await search_symbol_embeddings(
            self._db, query_embedding, max_results
        )

        # Resolve file hits to SearchResult
        file_results: list[SearchResult] = []
        for file_id, distance in file_hits:
            result = await self._resolve_file_hit(repo_id, file_id, distance)
            if result is not None:
                file_results.append(result)

        # Resolve symbol hits to SearchResult
        symbol_results: list[SearchResult] = []
        for symbol_id, distance in symbol_hits:
            result = await self._resolve_symbol_hit(repo_id, symbol_id, distance)
            if result is not None:
                symbol_results.append(result)

        # Merge, sort by distance (ascending = most similar first), take top N
        merged = file_results + symbol_results
        merged.sort(key=lambda r: r.score)
        return merged[:max_results]

    async def _resolve_file_hit(
        self, repo_id: int, file_id: int, distance: float
    ) -> SearchResult | None:
        """Look up file metadata for a vector search hit."""
        cursor = await self._db.execute(
            "SELECT path, summary FROM files WHERE id = ? AND repo_id = ?",
            (file_id, repo_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        path = str(row[0])
        summary = str(row[1]) if row[1] is not None else ""
        return SearchResult(
            kind="file",
            path=path,
            name=path,
            summary=summary,
            score=distance,
        )

    async def _resolve_symbol_hit(
        self, repo_id: int, symbol_id: int, distance: float
    ) -> SearchResult | None:
        """Look up symbol metadata for a vector search hit."""
        cursor = await self._db.execute(
            "SELECT s.name, s.summary, f.path "
            "FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.id = ? AND s.repo_id = ?",
            (symbol_id, repo_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        name = str(row[0])
        summary = str(row[1]) if row[1] is not None else ""
        path = str(row[2])
        return SearchResult(
            kind="symbol",
            path=path,
            name=name,
            summary=summary,
            score=distance,
        )
