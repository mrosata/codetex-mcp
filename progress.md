# Progress

## US-001: Project scaffold, dependencies, and error hierarchy

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Verified all pyproject.toml runtime, optional, and dev dependencies match the architecture spec
- Verified all package directories exist with `__init__.py` files under `src/codetex_mcp/`: cli/, server/, core/, analysis/, llm/, embeddings/, storage/, git/, config/
- Added missing `__init__.py` to `storage/migrations/` directory
- Verified `src/codetex_mcp/__main__.py` exists and calls `cli.app:main`
- Verified `src/codetex_mcp/exceptions.py` defines all 11 exception classes with correct inheritance:
  - `CodetexError` (base)
  - `RepositoryNotFoundError`, `RepositoryAlreadyExistsError` → CodetexError
  - `GitError` → CodetexError; `GitAuthError` → GitError (with setup guidance message)
  - `IndexError` → CodetexError
  - `LLMError` → CodetexError; `RateLimitError` → LLMError
  - `ConfigError`, `DatabaseError`, `EmbeddingError`, `NoIndexError` → CodetexError
- Verified `[project.scripts]` entry: `codetex = "codetex_mcp.cli.app:main"`
- mypy passes with no issues (14 source files checked)
- No tests exist yet (they start from US-002 onward)

### Notes for next developer
- Dev dependencies install via `uv sync --extra dev` (they're under `[project.optional-dependencies]` not `[dependency-groups]`)
- The `cli/app.py` is a stub with just a Typer app definition — commands come in US-018/US-019
- Next priority: **US-002** (Configuration settings with TOML loading and env overrides) in `config/settings.py`
- Architecture reference: `tasks/architecture.md` §3.9.1 and §8 for config schema

## US-002: Configuration settings with TOML loading and env overrides

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/config/settings.py` with `Settings` dataclass containing all fields per architecture spec:
  - `data_dir`, `repos_dir`, `db_path` (storage paths with derived defaults)
  - `llm_provider`, `llm_model`, `llm_api_key` (LLM config)
  - `max_file_size_kb`, `max_concurrent_llm_calls`, `tier1_rebuild_threshold`, `default_excludes` (indexing config)
  - `embedding_model` (embedding config)
- Implemented `Settings.load()` classmethod with 3-layer override: hardcoded defaults → `~/.codetex/config.toml` → env vars (last wins)
- TOML parsing uses `tomllib` (stdlib). Invalid TOML raises `ConfigError`
- Env vars: `CODETEX_DATA_DIR`, `CODETEX_LLM_PROVIDER`, `CODETEX_LLM_MODEL`, `ANTHROPIC_API_KEY`, `CODETEX_MAX_FILE_SIZE_KB`, `CODETEX_MAX_CONCURRENT_LLM`, `CODETEX_TIER1_THRESHOLD`, `CODETEX_EMBEDDING_MODEL`
- `load()` creates `data_dir` and `repos_dir` if they don't exist
- Key implementation detail: `CODETEX_DATA_DIR` env var is checked early in `load()` so the TOML file is found at the overridden path
- Created test suite: `tests/test_config/test_settings.py` with 27 tests across 4 classes:
  - `TestSettingsDefaults` (12 tests) — all default values
  - `TestSettingsTomlOverride` (4 tests) — full override, partial override, invalid TOML, tilde expansion
  - `TestSettingsEnvOverride` (8 tests) — each env var individually
  - `TestSettingsLoad` (3 tests) — directory creation, TOML+env layering, no config file
- mypy passes (15 source files, no issues)
- All 27 tests pass

### Notes for next developer
- `repos_dir` and `db_path` are derived from `data_dir` in `__post_init__` and again after all overrides in `load()` — they always follow `data_dir`
- TOML `[indexing] exclude_patterns` replaces (not extends) the default excludes list
- Next priority: **US-003** (Ignore filter for file exclusion) in `config/ignore.py`
- Architecture reference: `tasks/architecture.md` §3.9.2 for IgnoreFilter details

## US-003: Ignore filter for file exclusion

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/config/ignore.py` with `IgnoreFilter` class
- Constructor: `__init__(repo_path: Path, default_excludes: list[str], max_file_size_kb: int)`
- `is_excluded(file_path: Path) -> tuple[bool, str | None]` — returns `(True, reason)` or `(False, None)`
- `filter_files(files: list[str]) -> list[str]` — returns only non-excluded files
- 5-stage filter chain applied in order:
  1. Default excludes (from Settings)
  2. `.gitignore` rules (via `pathspec` library, `gitignore` pattern type)
  3. `.codetexignore` rules (same syntax)
  4. Max file size check (compares against `max_file_size_kb * 1024`)
  5. Binary detection (null byte in first 8 KB)
- `.codetexignore` supports `!pattern` negation syntax to override `.gitignore` exclusions
- Negation patterns are parsed separately and checked during gitignore/codetexignore stages
- Uses `pathspec` library with `gitignore` pattern type (not deprecated `gitwildmatch`)
- Created test suite: `tests/test_config/test_ignore.py` with 22 tests across 7 classes:
  - `TestDefaultExcludes` (4 tests) — node_modules, __pycache__, *.min.js, normal file passes
  - `TestGitignore` (4 tests) — file match, directory match, non-match, missing .gitignore
  - `TestCodetexignore` (3 tests) — positive match, negation overrides gitignore, negation doesn't affect others
  - `TestSizeThreshold` (3 tests) — large file, small file, exact threshold boundary
  - `TestBinaryDetection` (3 tests) — binary excluded, text passes, null byte after 8KB not detected
  - `TestFilterFiles` (2 tests) — multiple files, empty input
  - `TestFilterChainOrder` (3 tests) — default before gitignore, gitignore before size, nonexistent file handling
- mypy passes (16 source files, no issues)
- All 49 tests pass (22 new + 27 existing)

### Notes for next developer
- `IgnoreFilter` takes `max_file_size_kb` directly (not the full Settings object) for testability
- Size and binary checks are skipped if the file doesn't exist on disk (returns not-excluded)
- The `pathspec` library handles gitignore-style pattern matching including `**`, `!` negation in ignore files, trailing `/` for directories
- However, negation handling required custom logic: `pathspec.PathSpec.from_lines` treats `!patterns` as non-matching rather than truly negating, so negation patterns are parsed into a separate PathSpec and checked explicitly
- Next priority: **US-004** (Database foundation with migrations) in `storage/database.py`
- Architecture reference: `tasks/architecture.md` §3.7 and §4 for schema details

## US-004: Database foundation with migrations

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/storage/database.py` with `Database` class:
  - `__init__(db_path: Path)` — stores path, initializes `_conn` to None
  - `connect()` — opens aiosqlite connection, enables WAL mode, enables foreign keys, loads sqlite-vec extension via `sqlite_vec.loadable_path()`, disables extension loading after
  - `close()` — closes connection, sets `_conn` to None; no-op if not connected
  - `conn` property — returns connection or raises `DatabaseError` if not connected
  - `execute(sql, params)` — delegates to connection
  - `executemany(sql, params_list)` — delegates to connection
  - `migrate()` — creates `schema_version` table if not exists, finds current version, discovers migration SQL files sorted by numeric prefix, applies unapplied ones in order, records version after each
- Created `src/codetex_mcp/storage/migrations/001_initial.sql` with all tables per architecture spec:
  - `repositories` — id, name (UNIQUE), remote_url, local_path, default_branch, indexed_commit, last_indexed_at, created_at
  - `files` — id, repo_id (FK CASCADE), path, language, lines_of_code, token_count, role, summary, imports_json, updated_at; UNIQUE(repo_id, path); indexes idx_files_repo, idx_files_repo_path
  - `symbols` — id, file_id (FK CASCADE), repo_id (FK CASCADE), name, kind, signature, docstring, summary, start_line, end_line, parameters_json, return_type, calls_json, updated_at; indexes idx_symbols_file, idx_symbols_repo, idx_symbols_name
  - `dependencies` — id, repo_id (FK CASCADE), source_file_id (FK CASCADE), target_path, imported_names; UNIQUE(source_file_id, target_path); indexes idx_deps_repo, idx_deps_source
  - `repo_overviews` — id, repo_id (FK CASCADE), overview, directory_tree, technologies, commit_sha, created_at; UNIQUE(repo_id)
  - `vec_file_embeddings` — sqlite-vec virtual table with file_id PK and FLOAT[384] embedding
  - `vec_symbol_embeddings` — sqlite-vec virtual table with symbol_id PK and FLOAT[384] embedding
- Created test suite: `tests/test_storage/test_database.py` with 16 tests across 4 classes:
  - `TestConnect` (5 tests) — file creation, WAL mode, foreign keys, sqlite-vec loaded, conn property error
  - `TestClose` (2 tests) — conn set to None, close without connect
  - `TestExecute` (2 tests) — execute returns cursor, executemany inserts multiple rows
  - `TestMigrate` (7 tests) — tables created, vector tables created, idempotent, schema version recorded, indexes created, correct columns on all tables, foreign key cascades
- mypy passes (17 source files, no issues)
- All 65 tests pass (16 new + 49 existing)

### Notes for next developer
- sqlite-vec is loaded via `sqlite_vec.loadable_path()` (Python package provides the extension path) — no need to find the .so/.dylib manually
- Async fixtures for pytest-asyncio in strict mode require `@pytest_asyncio.fixture` decorator (not `@pytest.fixture`)
- `sqlite_vec` has no type stubs, so the import uses `# type: ignore[import-untyped]`
- `migrate()` uses `executescript()` for the SQL file (handles multiple statements) then separately `execute()` + `commit()` for the version insert
- All tables use `IF NOT EXISTS` for safety, but the migration runner also tracks versions so migrations won't re-run
- Next priority: **US-005** (Repository storage DAO) in `storage/repositories.py`
- Architecture reference: `tasks/architecture.md` §4.1 repositories table schema
