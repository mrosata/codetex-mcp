"""Full index pipeline orchestrator (9-step pipeline).

See architecture doc §3.3.2 and §5.1 for the pipeline specification.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from codetex_mcp.analysis.models import (
    FileAnalysis,
    ImportInfo,
    ParameterInfo,
    SymbolInfo,
)
from codetex_mcp.analysis.parser import Parser
from codetex_mcp.config.ignore import IgnoreFilter
from codetex_mcp.config.settings import Settings
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.exceptions import IndexError  # noqa: A004
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.llm.prompts import tier1_prompt, tier2_prompt, tier3_prompt
from codetex_mcp.llm.provider import LLMProvider
from codetex_mcp.storage.database import Database
from codetex_mcp.storage.files import (
    delete_dependencies_by_file,
    list_files,
    upsert_dependency,
    upsert_file,
    update_file_summary,
)
from codetex_mcp.storage.repositories import Repository, update_indexed_commit
from codetex_mcp.storage.symbols import (
    delete_symbols_by_file,
    list_symbols_by_file,
    upsert_symbol,
    update_symbol_summary,
)
from codetex_mcp.storage.vectors import (
    delete_file_embedding,
    delete_symbol_embedding,
    upsert_file_embedding,
    upsert_symbol_embedding,
)

ProgressCallback = Callable[[int, int, str], None]
StepCallback = Callable[[str], None]


@dataclass
class IndexResult:
    files_indexed: int
    symbols_extracted: int
    llm_calls_made: int
    tokens_used: int
    duration_seconds: float
    commit_sha: str


@dataclass
class _FileWork:
    """Internal: parsed file ready for storage and summarization."""

    path: str
    content: str
    analysis: FileAnalysis
    file_id: int = 0
    symbol_ids: list[tuple[int, SymbolInfo]] = field(default_factory=list)


class Indexer:
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

    async def index(
        self,
        repo: Repository,
        path_filter: str | None = None,
        dry_run: bool = False,
        on_progress: ProgressCallback | None = None,
        on_step: StepCallback | None = None,
    ) -> IndexResult:
        """Run the full 9-step indexing pipeline.

        Args:
            repo: Repository record from the database.
            path_filter: Optional prefix to restrict indexing scope.
            dry_run: If True, only runs Steps 1-2 and returns estimates.
            on_progress: Callback(current, total, file_path) for progress reporting.
            on_step: Callback(step_description) fired before each pipeline step.

        Returns:
            IndexResult with counts and timing.
        """
        start = time.monotonic()
        repo_id = repo.id
        repo_name = repo.name
        repo_path = Path(repo.local_path)

        def _step(msg: str) -> None:
            if on_step is not None:
                on_step(msg)

        try:
            # Step 1: Discover files
            _step("Discovering files...")
            file_paths = await self._discover_files(repo_path, path_filter)

            # Step 2: Parse each file
            _step(f"Parsing {len(file_paths)} files...")
            work_items = self._parse_files(file_paths, repo_path, on_progress)

            if dry_run:
                return self._build_dry_run_result(work_items, start)

            # Step 3: Store structure (file/symbol/dependency records)
            _step("Storing file structure...")
            await self._store_structure(work_items, repo_id)

            # Steps 4-5: LLM Tier 2 summaries
            _step(f"Generating file summaries ({len(work_items)} files)...")
            llm_calls_t2 = await self._summarize_tier2(work_items)

            # Steps 6-7: LLM Tier 3 summaries
            t3_count = sum(
                1
                for w in work_items
                for _, s in w.symbol_ids
                if s.kind in ("function", "method", "class")
            )
            _step(f"Generating symbol summaries ({t3_count} symbols)...")
            llm_calls_t3 = await self._summarize_tier3(work_items)

            # Step 8: Generate embeddings
            _step("Building embeddings...")
            await self._generate_embeddings(work_items, repo_id)

            # Step 9: Tier 1 overview + update commit
            _step("Generating repository overview...")
            commit_sha = await self._git.get_head_commit(repo_path)
            llm_calls_t1 = await self._generate_tier1(
                repo_id,
                repo_name,
                commit_sha,
            )

            await update_indexed_commit(self._db, repo_id, commit_sha)

            total_symbols = sum(len(w.symbol_ids) for w in work_items)
            total_tokens = sum(w.analysis.token_count for w in work_items)

            return IndexResult(
                files_indexed=len(work_items),
                symbols_extracted=total_symbols,
                llm_calls_made=llm_calls_t2 + llm_calls_t3 + llm_calls_t1,
                tokens_used=total_tokens,
                duration_seconds=time.monotonic() - start,
                commit_sha=commit_sha,
            )
        except IndexError:
            raise
        except Exception as exc:
            raise IndexError(f"Indexing failed: {exc}") from exc

    # -- Step 1: Discover files -----------------------------------------------

    async def _discover_files(
        self,
        repo_path: Path,
        path_filter: str | None,
    ) -> list[str]:
        tracked = await self._git.list_tracked_files(repo_path)
        ignore = IgnoreFilter(
            repo_path=repo_path,
            default_excludes=self._config.default_excludes,
            max_file_size_kb=self._config.max_file_size_kb,
        )
        filtered = ignore.filter_files(tracked)

        if path_filter is not None:
            filtered = [f for f in filtered if f.startswith(path_filter)]

        return filtered

    # -- Step 2: Parse files --------------------------------------------------

    def _parse_files(
        self,
        file_paths: list[str],
        repo_path: Path,
        on_progress: ProgressCallback | None,
    ) -> list[_FileWork]:
        total = len(file_paths)
        work_items: list[_FileWork] = []
        for i, rel_path in enumerate(file_paths):
            if on_progress is not None:
                on_progress(i + 1, total, rel_path)
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

    # -- Dry run result -------------------------------------------------------

    def _build_dry_run_result(
        self,
        work_items: list[_FileWork],
        start: float,
    ) -> IndexResult:
        total_symbols = sum(len(w.analysis.symbols) for w in work_items)
        summarizable_symbols = sum(
            1
            for w in work_items
            for s in w.analysis.symbols
            if s.kind in ("function", "method", "class")
        )
        estimated_llm_calls = len(work_items) + summarizable_symbols + 1
        total_tokens = sum(w.analysis.token_count for w in work_items)

        return IndexResult(
            files_indexed=len(work_items),
            symbols_extracted=total_symbols,
            llm_calls_made=estimated_llm_calls,
            tokens_used=total_tokens,
            duration_seconds=time.monotonic() - start,
            commit_sha="(dry run)",
        )

    # -- Step 3: Store structure ----------------------------------------------

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

            work.file_id = file_id

            # Clear old vec embeddings, symbols, and dependencies before
            # re-inserting.  Vec0 virtual tables don't participate in FK
            # cascades, so embeddings must be deleted explicitly first.
            existing_symbols = await list_symbols_by_file(self._db, file_id)
            for old_sym in existing_symbols:
                await delete_symbol_embedding(self._db, old_sym.id)
            await delete_file_embedding(self._db, file_id)

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

    # -- Steps 4-5: Tier 2 (file summaries) ----------------------------------

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

    # -- Steps 6-7: Tier 3 (symbol summaries) ---------------------------------

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

    # -- Step 8: Generate embeddings ------------------------------------------

    async def _generate_embeddings(
        self,
        work_items: list[_FileWork],
        repo_id: int,
    ) -> None:
        # Embed file summaries — read updated records from DB
        file_records = await list_files(self._db, repo_id)
        file_texts: list[str] = []
        file_ids: list[int] = []
        for rec in file_records:
            text = rec.summary or rec.path
            file_texts.append(text)
            file_ids.append(rec.id)

        if file_texts:
            file_embeddings = self._embedder.embed_batch(file_texts)
            for fid, embedding in zip(file_ids, file_embeddings):
                await upsert_file_embedding(self._db, fid, embedding)

        # Embed symbol summaries
        sym_texts: list[str] = []
        sym_ids: list[int] = []
        for rec in file_records:
            symbols = await list_symbols_by_file(self._db, rec.id)
            for sym in symbols:
                text = sym.summary or f"{sym.kind} {sym.name}: {sym.signature}"
                sym_texts.append(text)
                sym_ids.append(sym.id)

        if sym_texts:
            sym_embeddings = self._embedder.embed_batch(sym_texts)
            for sid, embedding in zip(sym_ids, sym_embeddings):
                await upsert_symbol_embedding(self._db, sid, embedding)

    # -- Step 9: Tier 1 overview ----------------------------------------------

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


# -- Helpers ------------------------------------------------------------------


def _imports_to_json(imports: list[ImportInfo]) -> str:
    return json.dumps([{"module": imp.module, "names": imp.names} for imp in imports])


def _params_to_json(parameters: list[ParameterInfo]) -> str:
    return json.dumps(
        [
            {
                "name": p.name,
                "type": p.type_annotation,
                "default": p.default_value,
            }
            for p in parameters
        ]
    )


def _extract_role(summary: str) -> str:
    """Extract the role classification from a Tier 2 summary."""
    valid_roles = (
        "entry_point",
        "core_logic",
        "utility",
        "model",
        "configuration",
        "test",
        "documentation",
    )
    lower = summary.lower()
    for role in valid_roles:
        if role in lower:
            return role
    return "utility"


def _build_directory_tree(paths: list[str]) -> str:
    """Build a simple directory tree string from file paths."""
    if not paths:
        return "(empty)"

    tree: dict[str, object] = {}
    for path in sorted(paths):
        parts = path.split("/")
        node: dict[str, object] = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            child = node[part]
            assert isinstance(child, dict)
            node = child

    lines: list[str] = []
    _render_tree(tree, "", lines)
    return "\n".join(lines)


def _render_tree(
    node: dict[str, object],
    prefix: str,
    lines: list[str],
) -> None:
    entries = sorted(node.keys())
    for i, name in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        lines.append(f"{prefix}{connector}{name}")
        child = node[name]
        if isinstance(child, dict) and child:
            extension = "    " if is_last else "\u2502   "
            _render_tree(child, prefix + extension, lines)
