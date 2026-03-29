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

## US-005: Repository storage DAO

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/storage/repositories.py` with:
  - `Repository` dataclass with fields matching the repositories table columns: `id`, `name`, `remote_url`, `local_path`, `default_branch`, `indexed_commit`, `last_indexed_at`, `created_at`
  - `create_repo(db, name, remote_url, local_path, default_branch) -> Repository` — inserts a new repository, raises `RepositoryAlreadyExistsError` on unique constraint violation
  - `get_repo_by_name(db, name) -> Repository | None` — fetches by name, returns None if not found
  - `list_repos(db) -> list[Repository]` — returns all repos ordered by name
  - `update_indexed_commit(db, repo_id, commit_sha)` — sets `indexed_commit` and `last_indexed_at = datetime('now')`
  - `delete_repo(db, repo_id)` — deletes by ID
  - Internal `_row_to_repo()` helper converts aiosqlite rows to `Repository` dataclass
- Created test suite: `tests/test_storage/test_repositories.py` with 11 tests across 5 classes:
  - `TestCreateRepo` (3 tests) — returns Repository with correct fields, handles None remote_url, raises on duplicate name
  - `TestGetRepoByName` (2 tests) — finds existing repo, returns None for nonexistent
  - `TestListRepos` (2 tests) — empty list, multiple repos ordered by name
  - `TestUpdateIndexedCommit` (2 tests) — sets commit and timestamp, overwrites previous commit
  - `TestDeleteRepo` (2 tests) — removes repo, no error on nonexistent ID
- mypy passes (18 source files, no issues)
- All 76 tests pass (11 new + 65 existing)

### Notes for next developer
- `_row_to_repo` uses `Any` type annotation for the row parameter to satisfy mypy (aiosqlite's `Row` type isn't exactly `tuple[object, ...]`)
- The test fixture includes `await database.migrate()` since the DAO depends on the tables existing
- `create_repo` catches `UNIQUE constraint failed` in the exception message to detect duplicates and re-raises as `RepositoryAlreadyExistsError`
- `delete_repo` on a nonexistent ID is a no-op (SQLite DELETE with no matching rows doesn't error)
- Next priority: **US-006** (File, symbol, and dependency storage DAOs) in `storage/files.py` and `storage/symbols.py`
- Architecture reference: `tasks/architecture.md` §4.1 for files, symbols, dependencies table schemas

## US-006: File, symbol, and dependency storage DAOs

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/storage/files.py` with:
  - `FileRecord` dataclass with fields matching the files table columns: `id`, `repo_id`, `path`, `language`, `lines_of_code`, `token_count`, `role`, `summary`, `imports_json`, `updated_at`
  - `upsert_file(db, repo_id, path, language, lines_of_code, token_count, imports_json) -> file_id` — uses ON CONFLICT(repo_id, path) DO UPDATE for upsert
  - `update_file_summary(db, file_id, summary, role)` — sets summary and role
  - `get_file(db, repo_id, path) -> FileRecord | None`
  - `list_files(db, repo_id) -> list[FileRecord]` — ordered by path
  - `delete_file(db, file_id)`
  - `count_files(db, repo_id) -> int`
  - `get_total_tokens(db, repo_id) -> int` — SUM of token_count
  - `upsert_dependency(db, repo_id, source_file_id, target_path, imported_names_json)` — uses ON CONFLICT(source_file_id, target_path) DO UPDATE
  - `delete_dependencies_by_file(db, file_id)`
- Created `src/codetex_mcp/storage/symbols.py` with:
  - `SymbolRecord` dataclass with fields matching the symbols table columns: `id`, `file_id`, `repo_id`, `name`, `kind`, `signature`, `docstring`, `summary`, `start_line`, `end_line`, `parameters_json`, `return_type`, `calls_json`, `updated_at`
  - `upsert_symbol(db, file_id, repo_id, name, kind, signature, docstring, start_line, end_line, parameters_json, return_type, calls_json) -> symbol_id` — plain INSERT (no unique constraint on symbols; caller uses delete_symbols_by_file then re-inserts)
  - `update_symbol_summary(db, symbol_id, summary)`
  - `get_symbol(db, repo_id, name) -> SymbolRecord | None`
  - `list_symbols_by_file(db, file_id) -> list[SymbolRecord]` — ordered by start_line
  - `delete_symbols_by_file(db, file_id)`
- Created test suites:
  - `tests/test_storage/test_files.py` — 18 tests across 8 classes (UpsertFile, UpdateFileSummary, GetFile, ListFiles, DeleteFile, CountFiles, GetTotalTokens, Dependencies, CascadeDelete)
  - `tests/test_storage/test_symbols.py` — 10 tests across 6 classes (UpsertSymbol, UpdateSymbolSummary, GetSymbol, ListSymbolsByFile, DeleteSymbolsByFile, CascadeBehavior)
- mypy passes (20 source files, no issues)
- All 104 tests pass (28 new + 76 existing)

### Notes for next developer
- The symbols table has no UNIQUE constraint beyond the primary key, so `upsert_symbol` is a plain INSERT. The expected usage pattern is: `delete_symbols_by_file` first to clear stale symbols, then insert fresh ones during re-indexing
- The files table has `UNIQUE(repo_id, path)` which enables true ON CONFLICT upsert behavior
- The dependencies table has `UNIQUE(source_file_id, target_path)` which enables ON CONFLICT upsert
- Both `delete_file` and `delete_symbols_by_file` on nonexistent IDs are no-ops (SQLite DELETE with no matching rows doesn't error)
- Foreign key CASCADE ensures that deleting a file automatically deletes its symbols and dependencies
- `get_total_tokens` uses `COALESCE(SUM(...), 0)` to return 0 for empty repos instead of None
- Next priority: **US-007** (Vector storage DAO) in `storage/vectors.py`
- Architecture reference: `tasks/architecture.md` §4.2 for sqlite-vec virtual table schema and query patterns

## US-007: Vector storage DAO

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/storage/vectors.py` with:
  - `_serialize_f32(vector: list[float]) -> bytes` — converts float list to compact raw bytes via `struct.pack` for sqlite-vec
  - `upsert_file_embedding(db, file_id, embedding)` — inserts or replaces a file embedding in `vec_file_embeddings`
  - `upsert_symbol_embedding(db, symbol_id, embedding)` — inserts or replaces a symbol embedding in `vec_symbol_embeddings`
  - `delete_file_embedding(db, file_id)` — deletes a file embedding by file_id
  - `delete_symbol_embedding(db, symbol_id)` — deletes a symbol embedding by symbol_id
  - `search_file_embeddings(db, query_embedding, limit) -> list[tuple[int, float]]` — KNN search returning (file_id, distance) ordered by distance
  - `search_symbol_embeddings(db, query_embedding, limit) -> list[tuple[int, float]]` — KNN search returning (symbol_id, distance) ordered by distance
- Created test suite: `tests/test_storage/test_vectors.py` with 13 tests across 6 classes:
  - `TestUpsertFileEmbedding` (2 tests) — insert, upsert replaces existing
  - `TestUpsertSymbolEmbedding` (2 tests) — insert, upsert replaces existing
  - `TestDeleteFileEmbedding` (2 tests) — delete removes embedding, delete nonexistent is no-op
  - `TestDeleteSymbolEmbedding` (2 tests) — delete removes embedding, delete nonexistent is no-op
  - `TestSearchFileEmbeddings` (3 tests) — nearest neighbors ordered by distance, respects limit, empty table returns empty list
  - `TestSearchSymbolEmbeddings` (2 tests) — nearest neighbors ordered by distance, empty table returns empty list
- mypy passes (21 source files, no issues)
- All 117 tests pass (13 new + 104 existing)

### Notes for next developer
- **Important:** `vec0` virtual tables do NOT support `ON CONFLICT`/UPSERT syntax. The upsert functions use a delete-then-insert pattern instead
- Embeddings are serialized to raw bytes via `struct.pack(f"{len(vector)}f", *vector)` — this is the compact binary format sqlite-vec expects (much more efficient than JSON)
- Search uses `WHERE embedding MATCH ? ORDER BY distance LIMIT ?` — the `MATCH` keyword triggers the KNN search, and `distance` is a special column provided by sqlite-vec
- The distance metric is L2 (Euclidean) by default in sqlite-vec's vec0. The architecture doc mentions "cosine distance" but vec0's default is L2. For normalized vectors (which sentence-transformers produces), L2 and cosine distance give equivalent ordering, so search results are correctly ranked
- Test helper `_make_embedding(seed)` creates deterministic 384-dim vectors with `[seed + i * 0.001 for i in range(384)]` — different seeds produce meaningfully different vectors for nearest-neighbor testing
- Next priority: **US-008** (Git operations wrapper) in `git/operations.py`
- Architecture reference: `tasks/architecture.md` §3.8 for git subprocess wrapper specification

## US-008: Git operations wrapper

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/git/operations.py` with:
  - `DiffResult` dataclass with fields: `added: list[str]`, `modified: list[str]`, `deleted: list[str]`, `renamed: list[tuple[str, str]]`
  - `GitOperations` class with `__init__(config: Settings)`
  - `_run(*args, cwd)` private helper — runs `git` binary via `asyncio.create_subprocess_exec`, returns (stdout, stderr), raises `GitError` on non-zero exit
  - `_raise_git_error(args, stderr)` — detects auth failures ("Permission denied", "Authentication failed") during clone and raises `GitAuthError`, otherwise raises `GitError`
  - `clone(url, target_dir)` — clones a repository to the target directory
  - `get_head_commit(repo_path) -> str` — returns current HEAD SHA via `git rev-parse HEAD`
  - `get_default_branch(repo_path) -> str` — returns current branch via `git symbolic-ref --short HEAD`, falls back to `origin/HEAD` parsing, then to `"main"`
  - `get_remote_url(repo_path) -> str | None` — returns origin remote URL via `git remote get-url origin`, or None if no remote
  - `diff_commits(repo_path, from_sha, to_sha) -> DiffResult` — parses `git diff --name-status` output into categorized file changes
  - `_parse_diff_output(output) -> DiffResult` — static method parsing A/M/D/R status lines; handles rename scores (R095, R100, etc.)
  - `list_tracked_files(repo_path) -> list[str]` — returns tracked files via `git ls-files`
  - `is_git_repo(path) -> bool` — checks via `git rev-parse --is-inside-work-tree`, returns False for non-repos and nonexistent paths
- Created test suite: `tests/test_git/test_operations.py` with 29 tests across 9 classes:
  - `TestGetHeadCommit` (3 tests) — returns 40-char hex SHA, matches git rev-parse, raises on non-git dir
  - `TestGetDefaultBranch` (2 tests) — returns branch name, follows checkout to new branch
  - `TestGetRemoteUrl` (2 tests) — returns None for no remote, returns URL after adding origin
  - `TestDiffCommits` (5 tests) — added file, modified file, deleted file, renamed file, empty diff
  - `TestParseDiffOutput` (6 tests) — A/M/D/R individual statuses, mixed output, empty output
  - `TestListTrackedFiles` (3 tests) — lists tracked files, includes newly staged files, excludes untracked
  - `TestIsGitRepo` (3 tests) — true for git repo, false for non-repo, false for nonexistent path
  - `TestClone` (2 tests) — clones local repo successfully, raises GitError for invalid URL
  - `TestGitAuthError` (3 tests) — detects "Authentication failed", detects "Permission denied", non-auth errors raise plain GitError
- mypy passes (22 source files, no issues)
- All 146 tests pass (29 new + 117 existing)

### Notes for next developer
- All git operations use `asyncio.create_subprocess_exec("git", ...)` — no gitpython dependency
- Auth error detection only triggers for `clone` commands (other operations on local repos shouldn't hit auth issues)
- `get_default_branch` has a 3-level fallback: `symbolic-ref` (current branch) → `origin/HEAD` (remote default) → hardcoded `"main"`
- `_parse_diff_output` handles rename scores like `R095` and `R100` — it checks `status.startswith("R")` and expects tab-separated old/new paths
- Tests create real temporary git repos using `subprocess.run(["git", ...])` in fixtures — no mocking of git itself, which tests the actual subprocess integration
- The `is_git_repo` method catches both `GitError` (for non-git dirs) and `FileNotFoundError` (for nonexistent paths)
- Next priority: **US-009** (Analysis data models and fallback parser) in `analysis/models.py` and `analysis/fallback_parser.py`
- Architecture reference: `tasks/architecture.md` §3.4.3 and §3.4.4

## US-009: Analysis data models and fallback parser

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/analysis/models.py` with 4 dataclasses per architecture spec:
  - `ParameterInfo(name, type_annotation, default_value)` — parameter with optional type and default
  - `SymbolInfo(name, kind, signature, docstring, start_line, end_line, parameters, return_type, calls)` — kind is `Literal['function', 'method', 'class', 'variable', 'constant']`
  - `ImportInfo(module, names)` — import with module and optional imported names
  - `FileAnalysis(path, language, imports, symbols, lines_of_code, token_count)` — result of parsing a source file
- Created `src/codetex_mcp/analysis/fallback_parser.py` with `FallbackParser` class:
  - `parse(content: str, language: str | None) -> FileAnalysis` — main entry point
  - Symbol extraction via 9 regex patterns covering: Python `def`/`class`, JavaScript/TypeScript `function`/`class` (with `export`/`async`), Go `func` (including method receivers), Rust `fn`/`struct`/`enum`/`trait` (with `pub`), Java/C++ method signatures, Ruby `def`
  - Import extraction via 10 regex patterns covering: Python `import`/`from..import`, JavaScript `import..from`/`require`, Go `import`, Rust `use`, C/C++ `#include`, Ruby `require`/`require_relative`, Java `import` (including `static`)
  - Parameter parsing with type annotations, default values, and `self`/`cls` filtering
  - Docstring extraction (Python triple-quoted strings following symbol definitions)
  - End-line estimation using indentation (Python) or brace counting (C-like languages)
  - Token counting via tiktoken `cl100k_base` encoding (lazy-loaded encoder)
  - Line counting via `str.splitlines()`
- Import pattern ordering: more specific patterns (Java with semicolons, JS with quotes, Go with quotes) ordered before generic Python `import` pattern to avoid false matches
- Created test suites:
  - `tests/test_analysis/test_models.py` — 11 tests across 4 classes (ParameterInfo, SymbolInfo, ImportInfo, FileAnalysis)
  - `tests/test_analysis/test_fallback_parser.py` — 36 tests across 10 classes:
    - `TestPythonFunctionExtraction` (8 tests) — simple/parameterized/default-param/class/multiple/self-filtering/docstring/end-line
    - `TestJavaScriptFunctionExtraction` (5 tests) — simple/async/export/class/export-class
    - `TestGoFunctionExtraction` (3 tests) — simple/return-type/method-receiver
    - `TestRustFunctionExtraction` (3 tests) — simple/pub-return/struct
    - `TestImportExtraction` (9 tests) — Python import/from-import, JS import/require, Go, Rust, C include, Ruby require, Java static import
    - `TestLineCount` (3 tests) — multi-line/empty/single-line
    - `TestTokenCount` (3 tests) — nonzero/matches-tiktoken/empty
    - `TestLanguageNone` (2 tests) — unknown language still parses/path set to empty
    - `TestMixedContent` (1 test) — full file with imports, functions, classes, docstrings
- mypy passes (24 source files, no issues)
- All 193 tests pass (47 new + 146 existing)

### Notes for next developer
- The `FallbackParser.parse()` sets `path=""` — the caller (unified `Parser` in US-010) is responsible for setting the actual file path on the returned `FileAnalysis`
- Import pattern ordering matters: Java imports (with semicolons) must come before generic Python imports to avoid `import static` being parsed as a Python import of module `static`
- The tiktoken encoder is lazily loaded as a module-level singleton (`_encoder`) to avoid repeated initialization overhead
- Symbol end-line estimation is approximate: uses indentation for Python-like languages, brace counting for C-like languages
- `_parse_python_params` handles `self`/`cls` filtering, `*args`/`**kwargs` name cleanup, type annotations, and default values
- The `SymbolInfo.kind` field uses a `Literal` type, but the fallback parser only produces `"function"` and `"class"` kinds — `"method"`, `"variable"`, and `"constant"` kinds will come from the tree-sitter parser (US-010)
- Next priority: **US-010** (Tree-sitter parser and unified dispatcher) in `analysis/tree_sitter.py` and `analysis/parser.py`
- Architecture reference: `tasks/architecture.md` §3.4.1 and §3.4.2
