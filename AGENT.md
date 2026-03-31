# AGENT.md — Deep Guide for LLM Agents

This file explains everything an LLM agent needs to know to understand, modify, and extend this codebase. It complements `CLAUDE.md` (which covers setup and commands) with architectural details, conventions, and pitfalls.

## What This Project Does

codetex-mcp indexes Git repositories into a three-tier context hierarchy and serves that context to LLMs:

- **Tier 1 (Repo Overview):** Single LLM-generated summary of the whole repo — architecture, technologies, entry points. Stored in `repo_overviews` table.
- **Tier 2 (File Summaries):** Per-file LLM-generated summary — purpose, role, public interfaces. Stored in `files` table (`summary`, `role` columns).
- **Tier 3 (Symbol Details):** Per-symbol (function/class/method) LLM-generated summary — what it does, parameters, return types, call graph. Stored in `symbols` table (`summary` column).

Additionally, 384-dimensional embeddings are generated for file and symbol summaries, stored in sqlite-vec virtual tables, enabling semantic search.

## Project Status

All 20 core user stories (US-001 through US-020) are complete. The evaluation framework (US-021 through US-032) is also complete. Three future stories (US-033–US-035) for LLM-based A/B testing are documented but not implemented. There are 621 tests, mypy is clean across 41 source files.

## Source Layout

```
src/codetex_mcp/
├── __init__.py              # Empty package marker
├── __main__.py              # Calls cli.app:main
├── exceptions.py            # 12 exception classes, all inherit CodetexError
├── cli/
│   └── app.py               # Typer app: add, index, sync, context, status, list, serve, config
├── server/
│   └── mcp_server.py        # FastMCP with 7 tools (stdio transport)
├── core/
│   ├── __init__.py           # AppContext dataclass + create_app() factory
│   ├── repo_manager.py       # RepoManager: add_remote, add_local, list, get, remove
│   ├── indexer.py            # Indexer: 9-step full index pipeline
│   ├── syncer.py             # Syncer: 7-step incremental sync pipeline
│   ├── context_store.py      # ContextStore: read Tier 1/2/3 from DB
│   └── search_engine.py      # SearchEngine: semantic search via embeddings
├── analysis/
│   ├── models.py             # FileAnalysis, SymbolInfo, ImportInfo, ParameterInfo
│   ├── tree_sitter.py        # TreeSitterParser: AST parsing for 8 languages
│   ├── fallback_parser.py    # FallbackParser: regex-based fallback
│   └── parser.py             # Parser: unified dispatcher (try tree-sitter, fall back)
├── llm/
│   ├── prompts.py            # tier1_prompt, tier2_prompt, tier3_prompt templates
│   ├── provider.py           # Abstract LLMProvider + AnthropicProvider
│   └── rate_limiter.py       # RateLimiter: asyncio.Semaphore + exponential backoff
├── embeddings/
│   └── embedder.py           # Embedder: sentence-transformers wrapper (lazy loading)
├── storage/
│   ├── database.py           # Database: aiosqlite + WAL + sqlite-vec + migrations
│   ├── repositories.py       # Repository dataclass + CRUD functions
│   ├── files.py              # FileRecord dataclass + CRUD + dependency functions
│   ├── symbols.py            # SymbolRecord dataclass + CRUD functions
│   ├── vectors.py            # Vector upsert/delete/search (sqlite-vec)
│   └── migrations/
│       └── 001_initial.sql   # Creates all 6 tables + 2 vec tables
├── git/
│   └── operations.py         # GitOperations: subprocess git wrapper
├── config/
│   ├── settings.py           # Settings dataclass: TOML + env var loading
│   └── ignore.py             # IgnoreFilter: gitignore + codetexignore + defaults
└── benchmarks/
    ├── metrics.py             # IR metrics: precision@k, recall@k, MRR, nDCG
    ├── token_metrics.py       # Token metrics: count_tokens, compression_ratio, coverage
    ├── baselines.py           # Naive baselines: grep_search, raw_file_context
    └── report.py              # JSON result writer with git SHA + timestamps
```

## Dependency Injection / Wiring

There is no DI framework. `create_app()` in `core/__init__.py` manually wires everything:

```
Settings.load() → Database → connect + migrate
                → GitOperations
                → TreeSitterParser + FallbackParser → Parser
                → RateLimiter → AnthropicProvider
                → Embedder
                → RepoManager(db, git, config)
                → ContextStore(db)
                → SearchEngine(db, embedder)
                → Indexer(db, git, parser, llm, embedder, config)
                → Syncer(db, git, parser, llm, embedder, config)
```

All of this is returned in an `AppContext` dataclass. The CLI creates it per-command via `_get_app()`. The MCP server creates it once lazily via `_get_ctx()`.

## Database Schema

Single SQLite file (`~/.codetex/codetex.db`). WAL mode, foreign keys enabled, sqlite-vec loaded.

**6 regular tables:**
- `schema_version` — migration tracking
- `repositories` — repo metadata (name unique, local_path, indexed_commit, etc.)
- `files` — per-file data (repo_id FK, path, language, LOC, token_count, summary, role, imports_json)
- `symbols` — per-symbol data (file_id FK, repo_id FK, name, kind, signature, summary, parameters_json, etc.)
- `dependencies` — import relationships (source_file_id FK, target_path)
- `repo_overviews` — Tier 1 overview text per repo

**2 sqlite-vec virtual tables (vec0):**
- `vec_file_embeddings(file_id INTEGER PRIMARY KEY, embedding FLOAT[384])`
- `vec_symbol_embeddings(symbol_id INTEGER PRIMARY KEY, embedding FLOAT[384])`

**Key constraint:** `files` has `UNIQUE(repo_id, path)`. `symbols` does NOT have a unique constraint on name — multiple repos or files can have the same symbol name.

## Critical Pitfalls

### sqlite-vec

- `vec0` virtual tables do **NOT** support `ON CONFLICT` / UPSERT. You must delete-then-insert.
- Embeddings must be serialized to raw bytes: `struct.pack(f"{len(v)}f", *v)`. Not JSON, not lists.
- Search syntax: `WHERE embedding MATCH ? ORDER BY distance LIMIT ?`. `distance` is a virtual column.
- vec tables do **NOT** participate in foreign key cascades. When deleting a file, you must manually delete its embeddings first.

### SQLite UPSERT + lastrowid

- `cursor.lastrowid` is **NOT** updated when an UPSERT triggers `DO UPDATE`. The stale value can be any previous INSERT's rowid.
- After `INSERT ... ON CONFLICT DO UPDATE`, always query back: `SELECT id FROM files WHERE repo_id=? AND path=?`.
- This is documented SQLite behavior, not a bug.

### Async Fixtures (pytest)

- pytest-asyncio in strict mode requires `@pytest_asyncio.fixture` for async fixtures. Using `@pytest.fixture` on an async function will silently fail.
- Every DB test fixture must call `await database.migrate()` because DAOs depend on tables existing.

### Anthropic SDK typing

- `AnthropicProvider` must use `anthropic.types.MessageParam` for message dicts, not plain `dict[str, str]` — the SDK has typed overloads that mypy enforces.
- The `system` prompt must be passed as an explicit keyword arg, not inside a `**kwargs` dict.
- `summarize_batch` acquires the semaphore then calls `summarize` which does NOT acquire — this avoids self-deadlock.

### Tree-sitter

- `typed_parameter` nodes do NOT have a `name` field — find the first `identifier` child directly.
- `typed_default_parameter` DOES have a `name` field.
- Grammar loading: `importlib.import_module("tree_sitter_python")`, then `mod.language()` → `tree_sitter.Language(ptr)`.
- The `Parser` class is the public API. `TreeSitterParser` and `FallbackParser` are implementation details.

### Token counting

- tiktoken `cl100k_base` encoder is lazy-loaded as a module-level singleton (in both `fallback_parser.py` and `tree_sitter.py`, and `benchmarks/token_metrics.py`).

## Storage Layer Patterns

The storage layer uses a **DAO pattern** with standalone async functions (not methods on Database):

```python
# Every DAO function takes db: Database as first arg
async def upsert_file(db: Database, repo_id: int, path: str, ...) -> int:
async def get_file(db: Database, repo_id: int, path: str) -> FileRecord | None:
```

Records are plain dataclasses (`Repository`, `FileRecord`, `SymbolRecord`). Conversion from DB rows uses private `_row_to_*` helper functions.

Every write operation calls `await db.conn.commit()` after execution. This is intentional — operations are individually atomic.

## Indexing Pipeline (9 steps)

The `Indexer.index()` method in `core/indexer.py`:

1. **Discover files** — `git ls-files` filtered by `IgnoreFilter` + optional `path_filter`
2. **Parse files** — via `Parser.parse_file()` (tree-sitter or fallback), emits `on_progress` callback
3. **Store structure** — upsert file/symbol/dependency records to DB (delete-then-insert for re-index)
4. **Tier 2 prompts** — build `tier2_prompt()` for each file
5. **Tier 2 summarize** — `llm.summarize_batch()` with rate limiting
6. **Tier 3 prompts** — build `tier3_prompt()` for functions/methods/classes only (skip variables/constants)
7. **Tier 3 summarize** — `llm.summarize_batch()` with rate limiting
8. **Embed** — `embedder.embed_batch()` for file and symbol summaries, store in vec tables
9. **Tier 1 overview** — single LLM call with directory tree + all file summaries, store in `repo_overviews`

Helper functions shared with `syncer.py`: `_extract_role`, `_imports_to_json`, `_params_to_json`, `_build_directory_tree`.

## Sync Pipeline (7 steps)

The `Syncer.sync()` method in `core/syncer.py`:

1. **Check staleness** — compare `indexed_commit` with current `HEAD`; return early if equal
2. **Compute diff** — `git diff --name-status` filtered by `IgnoreFilter` + `path_filter`
3. **Delete** — remove records for deleted files (order: symbol embeddings → file embedding → file record)
4. **Re-analyze** — parse + store + summarize (Tier 2 + 3) for added/modified files
5. **Re-embed** — per-file `embed()` for changed files and their symbols
6. **Tier 1 rebuild** — only if `changed_files / total_files >= tier1_rebuild_threshold` (default 10%)
7. **Update commit** — set `indexed_commit` and `last_indexed_at`

## CLI Patterns

- Typer commands are synchronous. They bridge to async via `asyncio.run()`.
- Each command has a `try/except CodetexError` wrapping an inner async `_run()` function.
- `_get_app()` is separated out for test mockability: `patch("codetex_mcp.cli.app._get_app", ...)`.
- The `config set` command uses a custom `_write_toml()` function because `tomllib` is read-only (no `tomli_w` dependency).
- `config` is a Typer subgroup: `app.add_typer(config_app, name="config")`.

## MCP Server Patterns

- `_app_ctx` is a module-level global, lazily initialized by `_get_ctx()` on first tool call.
- All tool functions catch `CodetexError` and re-raise as `ValueError`. FastMCP wraps `ValueError` as `ToolError` automatically.
- Tests access tools via `server._tool_manager.list_tools()` and must use `pytest.raises(ToolError)`, not `ValueError`.
- Tool responses are structured markdown strings optimized for LLM consumption.

## Exception Hierarchy

```
CodetexError
├── RepositoryNotFoundError
├── RepositoryAlreadyExistsError
├── GitError
│   └── GitAuthError          # Includes setup guidance message
├── IndexError                 # noqa: A001 (shadows builtin)
├── LLMError
│   └── RateLimitError
├── ConfigError
├── DatabaseError
├── EmbeddingError
└── NoIndexError               # Repo exists but has no index
```

## Configuration

`Settings` loads in three layers (last wins): hardcoded defaults → `~/.codetex/config.toml` → environment variables.

Key env vars: `CODETEX_DATA_DIR`, `CODETEX_LLM_MODEL`, `ANTHROPIC_API_KEY`, `CODETEX_MAX_FILE_SIZE_KB`, `CODETEX_MAX_CONCURRENT_LLM`, `CODETEX_TIER1_THRESHOLD`, `CODETEX_EMBEDDING_MODEL`.

Key defaults: `data_dir=~/.codetex`, `llm_model=claude-sonnet-4-5-20250929`, `max_file_size_kb=512`, `max_concurrent_llm_calls=5`, `tier1_rebuild_threshold=0.10`, `embedding_model=all-MiniLM-L6-v2`.

## Supported Languages

Tree-sitter grammars are included for: Python, JavaScript, TypeScript, Go, Rust, Java, Ruby, C++.

The `Parser.detect_language()` method maps file extensions to language names (20+ extensions). Files with unrecognized extensions fall through to the regex-based `FallbackParser`.

## Test Organization

```
tests/
├── test_analysis/          # Parser, tree-sitter, fallback parser, models
├── test_cli/               # CLI commands via CliRunner
├── test_config/            # Settings, IgnoreFilter
├── test_core/              # Indexer, Syncer, ContextStore, SearchEngine, RepoManager
├── test_embeddings/        # Embedder
├── test_git/               # GitOperations
├── test_llm/               # Provider, RateLimiter, Prompts
├── test_server/            # MCP server tools
├── test_storage/           # Database, repositories, files, symbols, vectors
└── test_benchmarks/        # IR metrics, token metrics, baselines, report writer
```

Test patterns:
- Async tests use `@pytest.mark.asyncio`
- Async fixtures use `@pytest_asyncio.fixture`
- DB fixtures: create `Database(tmp_path / "test.db")`, call `connect()` + `migrate()`, yield, call `close()`
- Embedder tests mock `SentenceTransformer` via `patch("codetex_mcp.embeddings.embedder.SentenceTransformer", ...)`
- LLM tests mock `anthropic.AsyncAnthropic`
- Git tests mock `asyncio.create_subprocess_exec`
- CLI tests use Typer's `CliRunner` and mock `_get_app()` to inject test doubles

## Benchmarks

```
benchmarks/
├── conftest.py                      # Shared fixtures (load_fixture, results_dir)
├── fixtures/
│   ├── codetex_mcp/                 # Ground truth for this repo
│   │   ├── retrieval_queries.json   # 18 curated (query, expected_files) tuples
│   │   └── efficiency_tasks.json    # 12 curated (task, relevant_files) tuples
│   └── flask/                       # Ground truth for Flask (needs local clone)
├── results/                         # JSON output (gitignored)
├── test_retrieval_bench.py          # IR metrics benchmark runner
└── test_efficiency_bench.py         # Token efficiency benchmark runner
```

Run benchmarks: `uv run pytest benchmarks/ -m benchmark -v`

Benchmark runners use `@pytest.mark.benchmark` marker (registered in `pyproject.toml`). Results are JSON files with timestamp, git SHA, and metric values.

## Key Design Decisions

1. **No ORM** — raw SQL with aiosqlite. Dataclass records, standalone DAO functions.
2. **No DI framework** — manual wiring via `create_app()` factory.
3. **No GitPython** — subprocess-based git wrapper for simplicity.
4. **Lazy loading** — SentenceTransformer model and Anthropic client are constructed but not initialized until first use.
5. **Every file uses `from __future__ import annotations`** — for `X | Y` union syntax on Python 3.12.
6. **sqlite-vec type stubs don't exist** — imports use `# type: ignore[import-untyped]`.
7. **`IndexError` shadows the builtin** — suppressed with `# noqa: A001`.

## Adding a New Feature Checklist

1. Add source code under `src/codetex_mcp/<module>/`
2. Add tests under `tests/test_<module>/`
3. Run `uv run pytest tests/ -v` to verify
4. Run `uv run mypy src/` to typecheck
5. Run `uv run ruff check src/ tests/` to lint
6. If adding a CLI command: register in `cli/app.py`
7. If adding an MCP tool: register in `server/mcp_server.py`
8. If adding a DB table: create a new migration file in `storage/migrations/`
9. Update `prd.json` with a new user story if applicable
