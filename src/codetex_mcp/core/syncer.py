"""Incremental sync pipeline orchestrator (7-step pipeline).

See architecture doc §3.3.3 and §5.2 for the pipeline specification.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from codetex_mcp.analysis.models import FileAnalysis, SymbolInfo
from codetex_mcp.analysis.parser import Parser
from codetex_mcp.config.ignore import IgnoreFilter
from codetex_mcp.config.settings import Settings
from codetex_mcp.core.indexer import (
    _build_directory_tree,
    _extract_role,
    _imports_to_json,
    _params_to_json,
)
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.exceptions import IndexError  # noqa: A004
from codetex_mcp.git.operations import DiffResult, GitOperations
from codetex_mcp.llm.prompts import tier1_prompt, tier2_prompt, tier3_prompt
from codetex_mcp.llm.provider import LLMProvider
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.files import (
    count_files,
    delete_dependencies_by_file,
    delete_file,
    get_file,
    list_files,
    update_file_summary,
    upsert_dependency,
    upsert_file,
)
from codetex_mcp.storage.repositories import Repository, update_indexed_commit
from codetex_mcp.storage.symbols import (
    delete_symbols_by_file,
    list_symbols_by_file,
    update_symbol_summary,
    upsert_symbol,
)
from codetex_mcp.storage.vectors import (
    delete_file_embedding,
    delete_symbol_embedding,
    upsert_file_embedding,
    upsert_symbol_embedding,
)


@dataclass
class SyncResult:
    already_current: bool
    files_added: int
    files_modified: int
    files_deleted: int
    llm_calls_made: int
    tokens_used: int
    tier1_rebuilt: bool
    old_commit: str
    new_commit: str
    duration_seconds: float


@dataclass
class _FileWork:
    """Internal: parsed file ready for storage and summarization."""

    path: str
    content: str
    analysis: FileAnalysis
    file_id: int = 0
    symbol_ids: list[tuple[int, SymbolInfo]] = field(default_factory=list)


class Syncer:
    def __init__(
        self,
        db: Database,
        git: GitOperations,
        parser: Parser,
        llm: LLMProvider,
        embedder: Embedder,
        config: Settings,
    ) -> None:
        self._db = db
        self._git = git
        self._parser = parser
        self._llm = llm
        self._embedder = embedder
        self._config = config

    async def sync(
        self,
        repo: Repository,
        path_filter: str | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Run the 7-step incremental sync pipeline.

        Args:
            repo: Repository record from the database.
            path_filter: Optional prefix to restrict sync scope.
            dry_run: If True, computes diff and estimates without making LLM calls.

        Returns:
            SyncResult with change counts and timing.
        """
        start = time.monotonic()
        repo_id = repo.id
        repo_name = repo.name
        repo_path = Path(repo.local_path)

        try:
            # Step 1: Compare commits
            old_commit = repo.indexed_commit or ""
            new_commit = await self._git.get_head_commit(repo_path)

            if old_commit == new_commit:
                return SyncResult(
                    already_current=True,
                    files_added=0,
                    files_modified=0,
                    files_deleted=0,
                    llm_calls_made=0,
                    tokens_used=0,
                    tier1_rebuilt=False,
                    old_commit=old_commit,
                    new_commit=new_commit,
                    duration_seconds=time.monotonic() - start,
                )

            # Step 2: Compute diff, apply filters
            diff = await self._git.diff_commits(repo_path, old_commit, new_commit)
            diff = self._apply_filters(diff, repo_path, path_filter)

            total_changed = len(diff.added) + len(diff.modified) + len(diff.deleted)

            if dry_run:
                return self._build_dry_run_result(
                    diff,
                    old_commit,
                    new_commit,
                    start,
                )

            # Step 3: Delete removed files
            await self._delete_removed(diff.deleted, repo_id)

            # Step 4: Re-analyze added + modified files
            changed_paths = diff.added + diff.modified
            work_items = self._parse_files(changed_paths, repo_path)
            await self._store_structure(work_items, repo_id)

            # LLM Tier 2 summaries for changed files
            llm_calls_t2 = await self._summarize_tier2(work_items)

            # LLM Tier 3 summaries for changed symbols
            llm_calls_t3 = await self._summarize_tier3(work_items)

            # Step 5: Update embeddings for changed files/symbols
            await self._update_embeddings(work_items, repo_id)

            # Step 6: Conditional Tier 1 rebuild
            total_files = await count_files(self._db, repo_id)
            if total_files > 0:
                changed_ratio = total_changed / total_files
            else:
                changed_ratio = 1.0

            llm_calls_t1 = 0
            tier1_rebuilt = False
            if changed_ratio >= self._config.tier1_rebuild_threshold:
                llm_calls_t1 = await self._generate_tier1(
                    repo_id,
                    repo_name,
                    new_commit,
                )
                tier1_rebuilt = True

            # Step 7: Update commit
            await update_indexed_commit(self._db, repo_id, new_commit)

            total_tokens = sum(w.analysis.token_count for w in work_items)

            return SyncResult(
                already_current=False,
                files_added=len(diff.added),
                files_modified=len(diff.modified),
                files_deleted=len(diff.deleted),
                llm_calls_made=llm_calls_t2 + llm_calls_t3 + llm_calls_t1,
                tokens_used=total_tokens,
                tier1_rebuilt=tier1_rebuilt,
                old_commit=old_commit,
                new_commit=new_commit,
                duration_seconds=time.monotonic() - start,
            )
        except IndexError:
            raise
        except Exception as exc:
            raise IndexError(f"Sync failed: {exc}") from exc

    # -- Step 2: Apply filters to diff -----------------------------------------

    def _apply_filters(
        self,
        diff: DiffResult,
        repo_path: Path,
        path_filter: str | None,
    ) -> DiffResult:
        ignore = IgnoreFilter(
            repo_path=repo_path,
            default_excludes=self._config.default_excludes,
            max_file_size_kb=self._config.max_file_size_kb,
        )

        added = ignore.filter_files(diff.added)
        modified = ignore.filter_files(diff.modified)
        deleted = ignore.filter_files(diff.deleted)
        renamed = [
            (old, new) for old, new in diff.renamed if new in ignore.filter_files([new])
        ]

        if path_filter is not None:
            added = [f for f in added if f.startswith(path_filter)]
            modified = [f for f in modified if f.startswith(path_filter)]
            deleted = [f for f in deleted if f.startswith(path_filter)]
            renamed = [
                (old, new) for old, new in renamed if new.startswith(path_filter)
            ]

        return DiffResult(
            added=added,
            modified=modified,
            deleted=deleted,
            renamed=renamed,
        )

    # -- Step 3: Delete removed files ------------------------------------------

    async def _delete_removed(
        self,
        deleted_paths: list[str],
        repo_id: int,
    ) -> None:
        for path in deleted_paths:
            file_rec = await get_file(self._db, repo_id, path)
            if file_rec is None:
                continue

            # Delete vectors for symbols of this file
            symbols = await list_symbols_by_file(self._db, file_rec.id)
            for sym in symbols:
                await delete_symbol_embedding(self._db, sym.id)

            # Delete file embedding
            await delete_file_embedding(self._db, file_rec.id)

            # Delete file record (cascades to symbols and dependencies)
            await delete_file(self._db, file_rec.id)

    # -- Step 4: Parse changed files -------------------------------------------

    def _parse_files(
        self,
        file_paths: list[str],
        repo_path: Path,
    ) -> list[_FileWork]:
        work_items: list[_FileWork] = []
        for rel_path in file_paths:
            abs_path = repo_path / rel_path
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            analysis = self._parser.parse_file(Path(rel_path), content)
            work_items.append(
                _FileWork(path=rel_path, content=content, analysis=analysis),
            )
        return work_items

    # -- Store structure -------------------------------------------------------

    async def _store_structure(
        self,
        work_items: list[_FileWork],
        repo_id: int,
    ) -> None:
        for work in work_items:
            analysis = work.analysis
            imports = analysis.imports
            symbols = analysis.symbols

            imports_json = _imports_to_json(imports) if imports else None

            file_id = await upsert_file(
                self._db,
                repo_id=repo_id,
                path=work.path,
                language=analysis.language,
                lines_of_code=analysis.lines_of_code,
                token_count=analysis.token_count,
                imports_json=imports_json,
            )

            # ON CONFLICT UPDATE may not set lastrowid correctly — query back
            if file_id == 0:
                rec = await get_file(self._db, repo_id, work.path)
                assert rec is not None
                file_id = rec.id

            work.file_id = file_id

            # Clear old symbols and dependencies before re-inserting
            await delete_symbols_by_file(self._db, file_id)
            await delete_dependencies_by_file(self._db, file_id)

            for sym in symbols:
                params_json = (
                    _params_to_json(sym.parameters) if sym.parameters else None
                )
                calls_json = json.dumps(sym.calls) if sym.calls else None

                symbol_id = await upsert_symbol(
                    self._db,
                    file_id=file_id,
                    repo_id=repo_id,
                    name=sym.name,
                    kind=sym.kind,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    parameters_json=params_json,
                    return_type=sym.return_type,
                    calls_json=calls_json,
                )
                work.symbol_ids.append((symbol_id, sym))

            for imp in imports:
                names_json = json.dumps(imp.names) if imp.names else None
                await upsert_dependency(
                    self._db,
                    repo_id=repo_id,
                    source_file_id=file_id,
                    target_path=imp.module,
                    imported_names_json=names_json,
                )

    # -- Tier 2 (file summaries) -----------------------------------------------

    async def _summarize_tier2(self, work_items: list[_FileWork]) -> int:
        if not work_items:
            return 0

        prompts: list[str] = []
        for work in work_items:
            prompt = tier2_prompt(
                file_path=work.path,
                content=work.content,
                symbols=work.analysis.symbols,
            )
            prompts.append(prompt)

        summaries = await self._llm.summarize_batch(
            prompts,
            system="You are a code analyst. Produce concise, structured summaries.",
        )

        for work, summary in zip(work_items, summaries):
            role = _extract_role(summary)
            await update_file_summary(self._db, work.file_id, summary, role)

        return len(prompts)

    # -- Tier 3 (symbol summaries) ---------------------------------------------

    async def _summarize_tier3(self, work_items: list[_FileWork]) -> int:
        prompts: list[str] = []
        symbol_ids: list[int] = []

        for work in work_items:
            for symbol_id, sym in work.symbol_ids:
                if sym.kind not in ("function", "method", "class"):
                    continue
                prompt = tier3_prompt(symbol=sym, file_context=work.path)
                prompts.append(prompt)
                symbol_ids.append(symbol_id)

        if not prompts:
            return 0

        summaries = await self._llm.summarize_batch(
            prompts,
            system="You are a code analyst. Produce concise, structured summaries.",
        )

        for sym_id, summary in zip(symbol_ids, summaries):
            await update_symbol_summary(self._db, sym_id, summary)

        return len(prompts)

    # -- Step 5: Update embeddings ---------------------------------------------

    async def _update_embeddings(
        self,
        work_items: list[_FileWork],
        repo_id: int,
    ) -> None:
        for work in work_items:
            file_rec = await get_file(self._db, repo_id, work.path)
            if file_rec is None:
                continue
            text = file_rec.summary or file_rec.path
            embedding = self._embedder.embed(text)
            await upsert_file_embedding(self._db, file_rec.id, embedding)

            # Re-embed changed symbol summaries
            symbols = await list_symbols_by_file(self._db, file_rec.id)
            for sym in symbols:
                sym_text = sym.summary or f"{sym.kind} {sym.name}: {sym.signature}"
                sym_embedding = self._embedder.embed(sym_text)
                await upsert_symbol_embedding(self._db, sym.id, sym_embedding)

    # -- Step 6: Tier 1 overview -----------------------------------------------

    async def _generate_tier1(
        self,
        repo_id: int,
        repo_name: str,
        commit_sha: str,
    ) -> int:
        file_records = await list_files(self._db, repo_id)
        dir_tree = _build_directory_tree([f.path for f in file_records])

        file_summaries: list[str] = []
        technologies: set[str] = set()
        for f in file_records:
            if f.summary:
                file_summaries.append(f"**{f.path}**: {f.summary}")
            if f.language:
                technologies.add(f.language)

        prompt = tier1_prompt(
            repo_name=repo_name,
            directory_tree=dir_tree,
            file_summaries=file_summaries,
            technologies=sorted(technologies),
        )

        overview = await self._llm.summarize(
            prompt,
            system="You are a code analyst. Produce a clear repository overview.",
        )

        tech_json = json.dumps(sorted(technologies))
        await self._db.execute(
            "INSERT INTO repo_overviews (repo_id, overview, directory_tree, technologies, commit_sha) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(repo_id) DO UPDATE SET "
            "overview = excluded.overview, "
            "directory_tree = excluded.directory_tree, "
            "technologies = excluded.technologies, "
            "commit_sha = excluded.commit_sha, "
            "created_at = datetime('now')",
            (repo_id, overview, dir_tree, tech_json, commit_sha),
        )
        await self._db.conn.commit()

        return 1

    # -- Dry run ---------------------------------------------------------------

    def _build_dry_run_result(
        self,
        diff: DiffResult,
        old_commit: str,
        new_commit: str,
        start: float,
    ) -> SyncResult:
        changed = len(diff.added) + len(diff.modified)
        # Estimate: 1 LLM call per changed file (Tier 2) + ~1 per file (Tier 3) + 1 (Tier 1)
        estimated_llm_calls = changed * 2 + 1

        return SyncResult(
            already_current=False,
            files_added=len(diff.added),
            files_modified=len(diff.modified),
            files_deleted=len(diff.deleted),
            llm_calls_made=estimated_llm_calls,
            tokens_used=0,
            tier1_rebuilt=False,
            old_commit=old_commit,
            new_commit=new_commit,
            duration_seconds=time.monotonic() - start,
        )
