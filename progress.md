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

## US-010: Tree-sitter parser and unified dispatcher

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/analysis/tree_sitter.py` with `TreeSitterParser` class:
  - `__init__()` — initializes language cache dict
  - `_load_language(language)` — on-demand grammar loading via `importlib.import_module` for tree-sitter grammar packages (e.g., `tree_sitter_python`), caches `Language` object or `None` on failure
  - `is_language_supported(language) -> bool` — checks if grammar is available (triggers lazy load)
  - `parse(content, language) -> FileAnalysis` — full AST parsing, raises `ValueError` if language unsupported
  - Supports 8 languages: python, javascript, typescript, go, rust, java, ruby, cpp
  - Python-specific deep extraction:
    - Function/method signatures with full parameter parsing (identifier, typed_parameter, default_parameter, typed_default_parameter, list_splat_pattern, dictionary_splat_pattern)
    - Return type annotations
    - Docstrings (triple-quoted `"""` and `'''`, single and multi-line)
    - Class definitions with base class extraction from argument_list
    - Method vs function kind detection (based on whether definition is inside a class body)
    - Decorated definitions handled by unwrapping `decorated_definition` nodes
    - `self`/`cls` parameter filtering
  - Generic extraction for other languages: first-line signature, kind inference from node type
  - Import extraction for Python: `import`, `from..import` with names, aliased imports, wildcard imports
  - Token counting via tiktoken `cl100k_base` (lazy-loaded encoder, same pattern as fallback parser)
  - Line counting via `str.splitlines()`
- Created `src/codetex_mcp/analysis/parser.py` with `Parser` dispatcher class:
  - `__init__(tree_sitter_parser, fallback_parser)` — takes both parsers as dependencies
  - `detect_language(path: Path) -> str | None` — maps 20+ file extensions to language names:
    - `.py`/`.pyw` → python
    - `.js`/`.mjs`/`.cjs`/`.jsx` → javascript
    - `.ts`/`.tsx` → typescript
    - `.go` → go, `.rs` → rust, `.java` → java, `.rb` → ruby
    - `.cpp`/`.cc`/`.cxx`/`.c`/`.h`/`.hpp`/`.hxx` → cpp
  - `parse_file(path, content, language=None) -> FileAnalysis` — detects language from path if not provided, tries tree-sitter first (if language supported), falls back to FallbackParser, sets actual file path on result
- Created test suites:
  - `tests/test_analysis/test_tree_sitter.py` — 28 tests across 8 classes:
    - `TestLanguageSupport` (4 tests) — grammar availability, caching, unsupported cached as None
    - `TestPythonFunctionExtraction` (6 tests) — simple/params+return/defaults/self-cls excluded/args-kwargs/decorated
    - `TestPythonClassExtraction` (4 tests) — simple/bases/docstring/methods with kind detection
    - `TestPythonDocstringExtraction` (4 tests) — function/multiline/none/single-quoted
    - `TestPythonImportExtraction` (4 tests) — simple/from-import/wildcard/aliased
    - `TestPythonMetrics` (4 tests) — line count/token count/language set/path empty
    - `TestPythonFullFile` (1 test) — full file with imports, classes, methods, functions
    - `TestParseUnsupportedLanguage` (1 test) — raises ValueError for unknown language
  - `tests/test_analysis/test_parser.py` — 24 tests across 3 classes:
    - `TestDetectLanguage` (17 tests) — all extension mappings including case insensitivity
    - `TestParseFile` (5 tests) — path setting, language detection, override, fallback, symbol extraction
    - `TestTreeSitterFallbackDispatch` (2 tests) — tree-sitter used when available, fallback for unsupported
- mypy passes (26 source files, no issues)
- All 245 tests pass (52 new + 193 existing)

### Notes for next developer
- tree-sitter grammar packages are optional pip extras — install via `uv sync --extra tree-sitter-python` etc.
- The `TreeSitterParser` caches loaded languages: `Language` object on success, `None` on `ImportError`/`OSError`. Cache is per-instance, so creating a new `TreeSitterParser()` resets it
- **Important tree-sitter API gotcha:** In Python's grammar, `typed_parameter` nodes do NOT have a `name` field for the identifier child — it has no field name (`None`). Instead, find the first `identifier` child directly. `typed_default_parameter` DOES have a `name` field. This asymmetry required different extraction logic
- Python parsing tests are conditionally skipped if `tree-sitter-python` is not installed (via `pytest.mark.skipif`)
- Both `TreeSitterParser.parse()` and `FallbackParser.parse()` set `path=""` — the unified `Parser.parse_file()` sets the actual path after calling the underlying parser
- The `Parser` dispatcher is the intended public API — `TreeSitterParser` and `FallbackParser` are implementation details
- For non-Python languages, the tree-sitter parser uses a generic extractor that captures the first line as signature. Language-specific deep extraction (like Python's parameter parsing) can be added per-language as needed
- Next priority: **US-011** (LLM rate limiter, prompts, and provider) in `llm/rate_limiter.py`, `llm/prompts.py`, `llm/provider.py`
- Architecture reference: `tasks/architecture.md` §3.5

## US-011: LLM rate limiter, prompts, and provider

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/llm/rate_limiter.py` with `RateLimiter` class:
  - `__init__(max_concurrent, base_delay, max_delay)` — wraps `asyncio.Semaphore` for concurrency control
  - `acquire()` — blocks if at max concurrent capacity
  - `release()` — releases a slot and resets the consecutive rate limit counter
  - `handle_rate_limit()` — exponential backoff with jitter: `min(base_delay * 2^(n-1), max_delay)` then uniform random jitter in `[0, delay]`
  - Tracks `_consecutive_rate_limits` for progressive backoff; reset on `release()`
- Created `src/codetex_mcp/llm/prompts.py` with 3 tier prompt template functions:
  - `tier1_prompt(repo_name, directory_tree, file_summaries, technologies)` — repo overview prompt with technologies, directory tree, and file summaries; shows "unknown"/"no file summaries" placeholders for empty inputs
  - `tier2_prompt(file_path, content, symbols)` — file summary prompt with source code, extracted symbols (formatted with parameters, types, defaults, return types, line ranges); asks for Purpose, Public Interface, Dependencies, Role classification
  - `tier3_prompt(symbol, file_context)` — symbol detail prompt with docstring, parameters, return type, calls, file context; asks for Description, Parameters, Returns, Relationships; includes placeholders for missing fields
- Created `src/codetex_mcp/llm/provider.py` with:
  - `LLMProvider` abstract base class with `summarize(prompt, system)` and `summarize_batch(prompts, system)` abstract methods
  - `AnthropicProvider(api_key, model, rate_limiter)` implementation:
    - Uses `anthropic.AsyncAnthropic` client with `MessageParam` typed messages
    - `summarize()` — sends single prompt, extracts text from response content blocks, maps `anthropic.RateLimitError` → `RateLimitError`, `anthropic.APIError` → `LLMError`
    - `summarize_batch()` — launches concurrent tasks via `asyncio.gather`, each task acquires semaphore slot, retries automatically on rate limit with backoff, releases slot on completion
    - Default model: `claude-sonnet-4-5-20250929`, accepts custom `RateLimiter` or creates default
- Created test suites:
  - `tests/test_llm/test_rate_limiter.py` — 8 tests across 3 classes:
    - `TestAcquireRelease` (2 tests) — basic acquire/release, blocks at capacity
    - `TestConcurrencyLimiting` (2 tests) — max active never exceeds limit, all workers complete
    - `TestHandleRateLimit` (4 tests) — waits on rate limit, consecutive increases, release resets count, delay capped at max
  - `tests/test_llm/test_prompts.py` — 26 tests across 3 classes:
    - `TestTier1Prompt` (7 tests) — non-empty, repo name, technologies, directory tree, file summaries, empty tech/summary placeholders
    - `TestTier2Prompt` (7 tests) — non-empty, file path, content, symbols with params/defaults, empty symbols placeholder, role classification
    - `TestTier3Prompt` (12 tests) — non-empty, symbol name, parameters, return type, calls, docstring, file context, all placeholder checks, class kind
  - `tests/test_llm/test_provider.py` — 17 tests across 4 classes:
    - `TestLLMProviderABC` (3 tests) — cannot instantiate, must implement both methods
    - `TestAnthropicProviderInit` (4 tests) — api key, custom model, custom rate limiter, default rate limiter
    - `TestAnthropicProviderSummarize` (6 tests) — text extraction, system prompt passed/omitted, multiple blocks joined, rate limit error, API error
    - `TestAnthropicProviderSummarizeBatch` (4 tests) — all prompts return results, empty input, retry on rate limit, concurrency respected
- mypy passes (29 source files, no issues)
- All 296 tests pass (51 new + 245 existing)

### Notes for next developer
- `AnthropicProvider` uses `anthropic.types.MessageParam` for typed messages to satisfy mypy's strict overload checking on `messages.create()`
- The system prompt is passed as a separate keyword arg (not via kwargs dict) to match the Anthropic SDK's typed overloads — using a `dict[str, object]` with `**kwargs` fails mypy's overload resolution
- `RateLimiter._consecutive_rate_limits` resets to 0 on `release()`, so backoff resets after a successful call
- `summarize_batch` acquires the semaphore before calling `summarize`, and `summarize` itself does NOT acquire — this avoids double-acquisition deadlocks
- Rate limit retry in `summarize_batch` is a `while True` loop around `summarize()` — it retries indefinitely until success (the exponential backoff with max_delay prevents tight loops)
- Provider tests mock `provider._client.messages.create` directly with `AsyncMock` — no real API calls
- `random.uniform` uses the default PRNG (not cryptographic) for jitter, which is fine for backoff timing
- Next priority: **US-012** (Embeddings module) in `embeddings/embedder.py`
- Architecture reference: `tasks/architecture.md` §3.6

## US-012: Embeddings module

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/embeddings/embedder.py` with `Embedder` class:
  - `MODEL_NAME = "all-MiniLM-L6-v2"` and `DIMENSIONS = 384` class constants
  - `__init__()` — initializes `_model` to `None`; model is NOT loaded at construction time
  - `_load_model()` — lazily instantiates `SentenceTransformer(self.MODEL_NAME)` on first call; no-ops on subsequent calls; wraps failures in `EmbeddingError` with model name and troubleshooting guidance
  - `embed(text: str) -> list[float]` — calls `_load_model()`, encodes text with `normalize_embeddings=True`, returns `.tolist()` (384-dim float list)
  - `embed_batch(texts: list[str]) -> list[list[float]]` — same pattern, returns list of vectors; empty input short-circuits without loading model
  - `SentenceTransformer` imported at module level for patchability; only *instantiation* is lazy (deferred to `_load_model`)
- Created test suite: `tests/test_embeddings/test_embedder.py` with 19 tests across 6 classes:
  - `TestEmbedderConstants` (2 tests) — MODEL_NAME, DIMENSIONS
  - `TestLazyLoading` (4 tests) — model None at construction, loaded on first embed, loaded on first embed_batch, loaded only once
  - `TestModelLoadFailure` (3 tests) — raises EmbeddingError on ImportError, OSError, error message includes model name
  - `TestEmbed` (3 tests) — returns list[float], 384 dimensions, passes normalize_embeddings=True
  - `TestEmbedBatch` (5 tests) — correct count, list[float] elements, empty returns empty, empty does not load model, passes normalize_embeddings=True
  - `TestNormalization` (2 tests) — embed returns unit-length vector, embed_batch returns unit-length vectors
- mypy passes (30 source files, no issues)
- All 315 tests pass (19 new + 296 existing)

### Notes for next developer
- `SentenceTransformer` is imported at module level (not inside `_load_model`). This makes it patchable in tests via `unittest.mock.patch("codetex_mcp.embeddings.embedder.SentenceTransformer", ...)`. The import itself is lightweight — only instantiation triggers the ~23MB model download
- `_model` is typed as `SentenceTransformer | None` with `.encode()` calls using `# type: ignore[union-attr]` since mypy can't narrow past the `_load_model()` guard
- `normalize_embeddings=True` is passed to `encode()` so vectors are unit-length (L2 norm = 1.0), making them suitable for cosine similarity. sqlite-vec uses L2 distance by default, but for normalized vectors L2 and cosine distance give equivalent ranking
- Tests use `numpy` arrays with `MagicMock` for `SentenceTransformer` — no real model download during testing
- `embed_batch([])` returns `[]` immediately without calling `_load_model()` — this avoids unnecessary model initialization
- Next priority: **US-013** (RepoManager core service) in `core/repo_manager.py`
- Architecture reference: `tasks/architecture.md` §3.3.1

## US-013: RepoManager core service

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/core/repo_manager.py` with `RepoManager` class:
  - `__init__(db: Database, git: GitOperations, config: Settings)` — dependency injection, no DI framework
  - `add_remote(url: str) -> Repository` — derives repo name from URL basename (strips `.git` suffix and handles trailing slashes), checks for duplicate before cloning, clones to `config.repos_dir/<name>/`, gets default branch, records in DB via `create_repo` DAO
  - `add_local(path: Path) -> Repository` — resolves path, validates `is_git_repo`, derives name from `path.name`, fetches remote URL (may be None) and default branch, records in DB
  - Both add methods raise `RepositoryAlreadyExistsError` on duplicate name, checked before expensive operations (clone)
  - `list_repos() -> list[Repository]` — delegates to `list_repos` DAO
  - `get_repo(name: str) -> Repository` — delegates to `get_repo_by_name` DAO, raises `RepositoryNotFoundError` if None
  - `remove_repo(name: str) -> None` — calls `get_repo` (raises if not found), then `delete_repo` DAO; does NOT delete cloned files on disk
  - Helper functions: `_is_remote_url(target)` checks for `://` or `git@` prefix; `_repo_name_from_url(url)` handles HTTPS/SSH/trailing slash/`.git` suffix
- Created test suite: `tests/test_core/test_repo_manager.py` with 23 tests across 8 classes:
  - `TestIsRemoteUrl` (6 tests) — HTTPS, SSH, git protocol, absolute path, relative path, name only
  - `TestRepoNameFromUrl` (4 tests) — with/without .git suffix, SSH, trailing slash
  - `TestAddRemote` (3 tests) — clone+register with correct args, duplicate raises, clone failure propagates
  - `TestAddLocal` (4 tests) — register with remote URL, without remote, not-a-repo raises GitError, duplicate raises
  - `TestListRepos` (2 tests) — empty list, list after adding
  - `TestGetRepo` (2 tests) — existing repo, nonexistent raises RepositoryNotFoundError
  - `TestRemoveRepo` (2 tests) — remove existing (verified via get_repo failing after), remove nonexistent raises
- mypy passes (31 source files, no issues)
- All 338 tests pass (23 new + 315 existing)

### Notes for next developer
- `RepoManager` uses `AsyncMock(spec=GitOperations)` in tests — no real git subprocess calls. DB fixtures use real SQLite via `Database` with migration
- `add_remote` checks for duplicate name BEFORE cloning to avoid wasting time on a clone that would fail at DB insert
- `add_local` calls `path.resolve()` to normalize the path before storing — this ensures consistent `local_path` values regardless of how the path was specified
- The `_repo_name_from_url` function handles both HTTPS (`/`-separated) and SSH (`:`-separated) URLs by splitting on both
- `remove_repo` intentionally does NOT delete cloned files from disk — this matches the architecture spec and avoids data loss
- Next priority: **US-014** (ContextStore and SearchEngine core services) in `core/context_store.py` and `core/search_engine.py`
- Architecture reference: `tasks/architecture.md` §3.3.4 and §3.3.5

## US-014: ContextStore and SearchEngine core services

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/core/context_store.py` with `ContextStore` class:
  - `__init__(db: Database)` — takes only a Database instance (read-only service, no writes)
  - `get_repo_overview(repo_id) -> str | None` — queries `repo_overviews` table, returns overview text or None
  - `get_file_context(repo_id, file_path) -> FileContext | None` — queries `files` table + `symbols` table for the file's symbols, returns `FileContext` dataclass or None
  - `get_symbol_detail(repo_id, symbol_name) -> SymbolDetail | None` — joins `symbols` and `files` tables to get full symbol detail including file path, returns `SymbolDetail` dataclass or None
  - `get_repo_status(repo_id) -> RepoStatus` — queries `repositories`, `files`, and `symbols` tables for aggregate stats, returns `RepoStatus` dataclass
- Data models defined in `context_store.py`:
  - `FileContext(summary, role, imports, symbols: list[SymbolBrief], lines_of_code, token_count)`
  - `SymbolBrief(name, kind, signature, start_line, end_line)` — lightweight symbol info for file context
  - `SymbolDetail(signature, summary, parameters, return_type, calls, file_path, start_line)`
  - `RepoStatus(indexed_commit, files_indexed, symbols_indexed, total_tokens, last_indexed_at)`
- Created `src/codetex_mcp/core/search_engine.py` with `SearchEngine` class:
  - `__init__(db: Database, embedder: Embedder)` — takes database and embedder
  - `search(repo_id, query, max_results=10) -> list[SearchResult]` — embeds query via Embedder, searches both `vec_file_embeddings` and `vec_symbol_embeddings`, resolves hits by joining files/symbols tables, merges results, sorts by distance (ascending = most similar first), returns top-N
  - `SearchResult(kind: Literal["file", "symbol"], path, name, summary, score)` — unified result type
  - Private methods `_resolve_file_hit` and `_resolve_symbol_hit` look up metadata and filter by repo_id
- Created test suites:
  - `tests/test_core/test_context_store.py` — 13 tests across 4 classes:
    - `TestGetRepoOverview` (3 tests) — returns overview, returns None, nonexistent repo
    - `TestGetFileContext` (4 tests) — full context, missing file, includes symbols, null fields
    - `TestGetSymbolDetail` (3 tests) — full detail, missing symbol, file path join
    - `TestGetRepoStatus` (3 tests) — empty repo, populated repo, nonexistent repo
  - `tests/test_core/test_search_engine.py` — 10 tests across 2 classes:
    - `TestSearch` (8 tests) — empty index, file results, symbol results, merged results, sorted by score, max_results limit, embedder called with query, null summary handling
    - `TestSearchResult` (2 tests) — file result fields, symbol result fields
- mypy passes (33 source files, no issues)
- All 361 tests pass (23 new + 338 existing)

### Notes for next developer
- `ContextStore` is a read-only service — it only queries the database, never writes. The Indexer/Syncer are responsible for populating the data
- `RepoStatus` does NOT include `current_head` or `is_stale` fields — those require git access. The PRD acceptance criteria mention these, but adding git dependency to ContextStore would break the clean separation. The CLI/MCP layer can compare `indexed_commit` with `git.get_head_commit()` to determine staleness
- `SearchEngine.search()` queries both vector tables with `max_results` each, then merges and re-limits — this ensures fair representation of both file and symbol results in the final output
- Search results use `distance` as `score` (lower = more similar). For normalized vectors, L2 distance and cosine distance give equivalent ranking
- `_resolve_file_hit` and `_resolve_symbol_hit` filter by `repo_id` to avoid returning results from other repos (since vector tables are shared across repos)
- Test helpers `_insert_file_with_embedding` and `_insert_symbol_with_embedding` directly insert into both regular and vector tables — no need for the full indexing pipeline
- Next priority: **US-015** (Indexer — full index pipeline) in `core/indexer.py`
- Architecture reference: `tasks/architecture.md` §3.3.2 and §5.1

## US-015: Indexer — full index pipeline

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/core/indexer.py` with `Indexer` class orchestrating the 9-step full indexing pipeline:
  - `__init__(db, git, parser, llm, embedder, config)` — dependency injection with Database/GitOperations/Parser/LLMProvider/Embedder/Settings
  - `index(repo, path_filter=None, dry_run=False, on_progress=None) -> IndexResult` — main entry point
  - Step 1 (`_discover_files`): discovers files via `git ls-files` + `IgnoreFilter` + optional `path_filter` prefix
  - Step 2 (`_parse_files`): parses each file via `Parser` (tree-sitter or fallback), calls `on_progress(current, total, file_path)` callback
  - Step 3 (`_store_structure`): upserts file records, deletes old symbols/dependencies then re-inserts, stores dependency edges from imports. Handles `ON CONFLICT` lastrowid=0 by querying back for the actual file_id
  - Steps 4-5 (`_summarize_tier2`): LLM summarizes Tier 2 (file summaries) via rate-limited `summarize_batch`, stores summary + role classification extracted from summary text
  - Steps 6-7 (`_summarize_tier3`): LLM summarizes Tier 3 (symbol summaries) for functions/methods/classes only (skips variables/constants)
  - Step 8 (`_generate_embeddings`): generates embeddings for file and symbol summaries via `embed_batch`, stores in sqlite-vec
  - Step 9 (`_generate_tier1`): generates Tier 1 overview via single LLM call with directory tree and file summaries, stores in `repo_overviews` (upsert), updates `indexed_commit`
  - `dry_run=True` runs Steps 1-2 only, returns estimates (files, symbols, estimated LLM calls, token counts) without making API calls or DB writes
  - Error handling: wraps unexpected exceptions in `IndexError`, passes through `IndexError` directly
- Data models:
  - `IndexResult(files_indexed, symbols_extracted, llm_calls_made, tokens_used, duration_seconds, commit_sha)` — returned from `index()`
  - `_FileWork(path, content, analysis, file_id, symbol_ids)` — internal work item tracking parsed file through the pipeline
- Helper functions: `_imports_to_json`, `_params_to_json`, `_extract_role`, `_build_directory_tree`, `_render_tree`
- Created test suite: `tests/test_core/test_indexer.py` with 39 tests across 10 classes:
  - `TestIndexerInit` (1 test) — dependency injection
  - `TestFullIndex` (15 tests) — full pipeline: files/symbols/deps stored, tier2/tier3/tier1 LLM calls made, summaries stored, embeddings stored (file + symbol), repo overview stored, indexed commit updated, LLM call count, token count
  - `TestDryRun` (5 tests) — returns estimates, no LLM calls, no DB writes, no embeddings
  - `TestPathFilter` (2 tests) — restricts files, no-match returns 0
  - `TestProgressCallback` (1 test) — callback invoked with correct (current, total, path) args
  - `TestErrorHandling` (2 tests) — wraps unexpected errors, passes through IndexError
  - `TestTier3SymbolFiltering` (1 test) — skips variable symbols
  - `TestReindex` (1 test) — re-indexing upserts, not duplicates
  - `TestHelpers` (9 tests) — JSON serialization, role extraction, directory tree building
  - `TestIndexResult` (2 tests) — dataclass field access
- mypy passes (34 source files, no issues)
- All 400 tests pass (39 new + 361 existing)

### Notes for next developer
- **Re-index safety:** On re-index, `upsert_file` uses `ON CONFLICT(repo_id, path) DO UPDATE` which may return `lastrowid=0`. The Indexer detects this and queries back via `get_file()` to get the correct file_id. Old symbols and dependencies are deleted before re-inserting to prevent duplicates
- **Role extraction:** `_extract_role` searches the Tier 2 summary text for role keywords (entry_point, core_logic, utility, model, configuration, test, documentation) — defaults to "utility" if none found
- **Tier 3 filtering:** Only symbols with kind in `("function", "method", "class")` get Tier 3 summaries — variables and constants are skipped to save LLM calls
- **Embeddings:** Uses `embed_batch` for efficiency. File summaries default to file path if no summary exists. Symbol summaries default to `"{kind} {name}: {signature}"` if no summary exists
- **Directory tree:** `_build_directory_tree` builds a tree-style visualization with Unicode box-drawing characters (├── └── │)
- Tests mock all external dependencies (git, parser, LLM, embedder) — no real API calls, file system is limited to tmp_path
- Next priority: **US-016** (Syncer — incremental sync pipeline) in `core/syncer.py`
- Architecture reference: `tasks/architecture.md` §3.3.3 and §5.2

## US-016: Syncer — incremental sync pipeline

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Created `src/codetex_mcp/core/syncer.py` with `Syncer` class orchestrating the 7-step incremental sync pipeline:
  - `__init__(db, git, parser, llm, embedder, config)` — dependency injection with Database/GitOperations/Parser/LLMProvider/Embedder/Settings
  - `sync(repo, path_filter=None, dry_run=False) -> SyncResult` — main entry point
  - Step 1 (`sync`): compares `repo.indexed_commit` with current HEAD via `git.get_head_commit()`; returns `already_current=True` if equal
  - Step 2 (`_apply_filters`): computes git diff via `git.diff_commits()`, applies `IgnoreFilter` to added/modified/deleted/renamed lists, then applies optional `path_filter` prefix
  - Step 3 (`_delete_removed`): for each deleted file, deletes symbol embeddings first, then file embedding, then the file record (which cascades to symbols and dependencies)
  - Step 4 (`_parse_files` + `_store_structure` + `_summarize_tier2` + `_summarize_tier3`): re-analyzes added + modified files — parses AST, stores file/symbol/dependency records, LLM summarizes Tier 2 (file summaries) and Tier 3 (symbol summaries for functions/methods/classes)
  - Step 5 (`_update_embeddings`): re-embeds changed file summaries and their symbol summaries using `embed()` per item (not batch, since only changed files need updating)
  - Step 6 (conditional Tier 1 rebuild): computes `changed_ratio = total_changed / total_files`; if >= `tier1_rebuild_threshold`, regenerates Tier 1 overview via single LLM call
  - Step 7: updates `indexed_commit` and `last_indexed_at` in repositories table
  - `dry_run=True` computes diff and returns estimates without making LLM calls or DB writes
- Reuses helper functions from `core/indexer.py`: `_extract_role`, `_imports_to_json`, `_params_to_json`, `_build_directory_tree` — avoids code duplication
- Data models:
  - `SyncResult(already_current, files_added, files_modified, files_deleted, llm_calls_made, tokens_used, tier1_rebuilt, old_commit, new_commit, duration_seconds)` — returned from `sync()`
  - `_FileWork(path, content, analysis, file_id, symbol_ids)` — internal work item tracking parsed file through the pipeline
- Error handling: wraps unexpected exceptions in `IndexError`, passes through `IndexError` directly
- Created test suite: `tests/test_core/test_syncer.py` with 29 tests across 9 classes:
  - `TestSyncerInit` (1 test) — dependency injection
  - `TestAlreadyCurrent` (2 tests) — returns already_current, no diff called
  - `TestFullSync` (12 tests) — full pipeline: deletes removed files/symbols/embeddings, stores added files, updates modified files, LLM Tier 2+3 calls, embedding generation, indexed commit update, LLM call count, token count
  - `TestTier1Rebuild` (3 tests) — rebuilt when ratio exceeds threshold, not rebuilt when below threshold, stores overview
  - `TestDryRun` (5 tests) — returns estimates, no LLM calls, no DB writes, no embeddings, estimates LLM calls
  - `TestPathFilter` (2 tests) — restricts scope, no-match returns zeroes
  - `TestErrorHandling` (2 tests) — wraps unexpected errors, passes through IndexError
  - `TestNoIndex` (1 test) — sync with no prior index (indexed_commit=None) works
  - `TestSyncResult` (1 test) — dataclass field access
- mypy passes (35 source files, no issues)
- All 429 tests pass (29 new + 400 existing)

### Notes for next developer
- The Syncer reuses helper functions from `core/indexer.py` (`_extract_role`, `_imports_to_json`, `_params_to_json`, `_build_directory_tree`) to avoid code duplication. If these helpers need changes, update them in `indexer.py` and both modules benefit
- **Embedding strategy difference from Indexer:** The Syncer uses `embed()` per-file (not `embed_batch`) because it only processes changed files. The Indexer uses `embed_batch` for the entire repo. This is intentional — batch is more efficient for full index, per-item is simpler for incremental updates
- **Deletion order matters:** Symbol embeddings must be deleted before the file record, because `delete_file` cascades to symbols, which would leave orphan symbol embeddings in the vec table (sqlite-vec virtual tables don't participate in foreign key cascades)
- **Tier 1 rebuild threshold:** Uses `config.tier1_rebuild_threshold` (default 0.10 = 10%). The ratio is `(added + modified + deleted) / total_files_after_sync`. High ratios (many changes) trigger a rebuild; small changes (e.g., fixing one file in a 100-file repo) skip it to save LLM calls
- **No prior index edge case:** If `indexed_commit` is None (never indexed), the Syncer treats old_commit as `""` and proceeds with the diff. This works because `git diff ""..HEAD` will show all files as added
- Tests use `indexed_repo` fixture to pre-populate DB with file/symbol/embedding records, simulating a prior full index
- Next priority: **US-017** (Application wiring — AppContext and create_app) in `core/__init__.py`
- Architecture reference: `tasks/architecture.md` §10 for the full wiring specification

## US-017: Application wiring — AppContext and create_app

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Implemented `src/codetex_mcp/core/__init__.py` with:
  - `AppContext` dataclass with 11 fields: `settings` (Settings), `db` (Database), `git` (GitOperations), `parser` (Parser), `llm` (LLMProvider), `embedder` (Embedder), `repo_manager` (RepoManager), `indexer` (Indexer), `syncer` (Syncer), `context_store` (ContextStore), `search_engine` (SearchEngine)
  - `create_app(settings: Settings | None = None) -> AppContext` async factory function that wires the full object graph:
    - Loads Settings if not provided (via `Settings.load()`)
    - Creates Database, connects, and runs migrations
    - Creates GitOperations with settings
    - Creates Parser with TreeSitterParser + FallbackParser
    - Creates RateLimiter with `max_concurrent` from settings
    - Creates AnthropicProvider with API key, model, and rate limiter from settings
    - Creates Embedder (lazy model loading — no download at construction)
    - Creates RepoManager, ContextStore, SearchEngine, Indexer, Syncer with proper dependency wiring
    - Returns fully populated AppContext
  - LLM and embedder are constructed but defer heavy initialization to first use (lazy loading pattern)
- Created test suite: `tests/test_core/test_app_context.py` with 7 tests across 2 classes:
  - `TestAppContext` (1 test) — field access verification
  - `TestCreateApp` (6 tests) — returns AppContext, all fields populated with correct types, database migrated (schema_version check), uses provided settings, loads default settings when None (via env var override), core tables exist after migration
- mypy passes (35 source files, no issues)
- All 436 tests pass (7 new + 429 existing)

### Notes for next developer
- `settings.db_path` is `Path | None` in the type declaration, but always `Path` after `__post_init__`/`load()`. An `assert settings.db_path is not None` narrows the type for mypy
- `settings.llm_api_key` is `str | None` but `AnthropicProvider.__init__` requires `str`. We pass `settings.llm_api_key or ""` — the empty string is fine because the client is constructed lazily and only fails on first actual API call (commands like `list`, `status`, `config` never hit the LLM)
- `create_app` creates a `RateLimiter` wired with `settings.max_concurrent_llm_calls` — this isn't shown in the architecture doc's example but matches the `AnthropicProvider` constructor's optional `rate_limiter` parameter
- The DB connection is opened and migrations are run eagerly in `create_app` — this is the only "heavy" initialization at startup. LLM client setup and embedding model download are deferred
- Next priority: **US-018** (CLI commands — add, list, status, config) in `cli/app.py`
- Architecture reference: `tasks/architecture.md` §3.1 and §7 for CLI command mapping

## US-018: CLI commands — add, list, status, config

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Implemented `src/codetex_mcp/cli/app.py` with 4 commands and a config subcommand group:
  - `codetex add <target>` — detects remote URLs (contains `://` or starts with `git@`) vs local paths, dispatches to `RepoManager.add_remote` or `add_local`, prints success with repo name and local path
  - `codetex list` — displays a rich `Table` with columns: Name (bold), Remote URL, Indexed Commit (truncated to 12 chars), Last Indexed. Shows "No repositories registered." for empty list
  - `codetex status <repo>` — shows rich table with: Indexed Commit, Current HEAD (via `git.get_head_commit`), Stale (Yes/No/N/A), Files Indexed, Symbols Indexed, Total Tokens (comma-formatted), Last Indexed
  - `codetex config show` — displays all settings as a rich table. API key is masked as `***`; shown as `Not set` when None
  - `codetex config set <key> <value>` — validates key name against `_CONFIG_KEY_MAP` (8 valid keys), validates int/float types, reads and preserves existing TOML values, writes with proper TOML typing
- Config subcommand uses `typer.Typer` subgroup added via `app.add_typer(config_app, name="config")`
- Error handling: each async command catches `CodetexError` and calls `_handle_error()` which prints `"Error: {message}"` to stderr and raises `typer.Exit(code=1)`. `main()` also wraps `app()` in a `CodetexError` catch for the real entry point
- Custom `_write_toml()` function for TOML serialization since `tomllib` (stdlib) is read-only and no `tomli_w` dependency is added
- Async bridge: each command defines an inner `async def` and runs it via `asyncio.run()`. The `_get_app()` helper calls `create_app()` to wire services
- DB cleanup: all async commands use `try/finally` to ensure `ctx.db.close()` is called
- Created test suite: `tests/test_cli/test_app.py` with 24 tests across 7 classes:
  - `TestAddCommand` (4 tests) — add local, add remote, duplicate error, DB close
  - `TestListCommand` (3 tests) — list repos with data, empty list, DB close
  - `TestStatusCommand` (5 tests) — indexed repo, stale detection, not indexed, repo not found, DB close
  - `TestConfigShowCommand` (2 tests) — with API key (masked), without API key
  - `TestConfigSetCommand` (7 tests) — string value, int value, float value, unknown key, invalid int, preserves existing config, API key
  - `TestErrorHandling` (2 tests) — CodetexError caught, subclass caught
  - `TestMainFunction` (1 test) — main() exists and is callable
- mypy passes (35 source files, no issues)
- All 460 tests pass (24 new + 436 existing)

### Notes for next developer
- Typer commands are sync but call async services via `asyncio.run()`. Each command defines an inner `async def` that does the actual work
- Error handling is per-command (not just in `main()`) because Typer's `CliRunner` in tests invokes `app()` directly, not `main()`. The `try/except CodetexError` wraps the `_run()` call in each command
- `_get_app()` is a separate async function (not inline) so tests can mock it via `patch("codetex_mcp.cli.app._get_app", return_value=mock_ctx)`
- `config set` uses `_write_toml()` — a simple custom TOML writer. It handles strings (with escaping), booleans, int/float, and lists. More complex TOML features (nested tables, multiline strings) are not needed for our config schema
- `config show` masks the API key as `***` for security — it never displays the actual key
- The `status` command catches exceptions from `git.get_head_commit` silently — the repo directory might have been moved or deleted
- Staleness logic: compares `indexed_commit` with `current_head`. Shows "N/A" when not indexed, "Yes"/"No" when indexed
- Tests use `typer.testing.CliRunner` with mocked `_get_app` — no real database, git operations, or file system
- Next priority: **US-019** (CLI commands — index, sync, context, serve) in `cli/app.py`
- Architecture reference: `tasks/architecture.md` §3.1 and §7 for CLI command mapping

## US-019: CLI commands — index, sync, context, serve

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Added 4 new commands to `cli/app.py`: `index`, `sync`, `context`, `serve`
- **`codetex index <repo> [--path P] [--dry-run]`**: Triggers `Indexer.index` with rich Progress bar (spinner + file count + current file). `--dry-run` runs estimation only and displays a summary table (files to index, symbols found, estimated LLM calls, estimated tokens). Full run displays results table (files indexed, symbols extracted, LLM calls, tokens used, duration, commit SHA)
- **`codetex sync <repo> [--path P] [--dry-run]`**: Triggers `Syncer.sync`. Detects `already_current` and prints "Already up to date." Otherwise displays change summary table (files added/modified/deleted, LLM calls, tokens, tier1 rebuilt, old→new commit, duration). `--dry-run` shows estimates
- **`codetex context <repo> [--file F] [--symbol S] [--query Q]`**: Multi-mode context query:
  - No flags → Tier 1 overview rendered as rich Markdown
  - `--file` → Tier 2 file context (summary, role, LOC, tokens, symbols list)
  - `--symbol` → Tier 3 symbol detail (signature, file:line, summary, parameters, return type, calls)
  - `--query` → Semantic search via SearchEngine, results in scored table (score, kind, path, name, summary)
  - Missing file/symbol returns exit code 1 with descriptive error
  - Missing index returns "No index found" message
- **`codetex serve`**: Imports and runs FastMCP server via `create_server()` from `server/mcp_server.py`
- Created `server/mcp_server.py` with `create_server()` factory returning `FastMCP('codetex')` (tool registration deferred to US-020)
- Added `rich.markdown.Markdown` and `rich.progress.Progress/SpinnerColumn/TextColumn` imports

### Tests added
- 22 new tests across 5 test classes in `tests/test_cli/test_app.py`:
  - `TestIndexCommand` (5 tests) — full index, dry-run, path filter, repo not found, db close
  - `TestSyncCommand` (6 tests) — changes summary, already current, dry-run, path filter, repo not found, db close
  - `TestContextCommand` (10 tests) — overview, not-indexed, file context, file not found, symbol detail, symbol not found, search results, search empty, repo not found, db close
  - `TestServeCommand` (1 test) — creates and runs server
- mypy passes (36 source files, no issues)
- All 482 tests pass (22 new + 460 existing)

### Notes for next developer
- The `index` command uses `on_progress` callback to update the rich Progress bar. The callback receives `(current, total, file_path)` and updates the progress task
- The `serve` command uses a lazy import of `create_server` inside the function body to avoid importing MCP server code unless needed
- The `context` command prioritizes `--query` > `--file` > `--symbol` > overview when multiple flags are given
- `server/mcp_server.py` is a minimal stub — just `FastMCP('codetex')`. US-020 will add the 7 tools
- Next priority: **US-020** (MCP server with 7 tools) in `server/mcp_server.py`
- Architecture reference: `tasks/architecture.md` §3.2 and §6 for MCP tool signatures

## US-020: MCP server with 7 tools

**Status:** Complete
**Date:** 2026-03-29

### What was done
- Replaced the `server/mcp_server.py` stub with full implementation: `FastMCP('codetex')` server with 7 registered tools
- Module-level `_app_ctx: AppContext | None` with lazy initialization via `_get_ctx()` — calls `create_app()` once on first tool invocation and reuses the context for all subsequent calls
- **7 tools registered:**
  1. `get_repo_overview(repo_name)` — returns Tier 1 markdown overview; raises `NoIndexError` → `ValueError` if no index exists
  2. `get_file_context(repo_name, file_path)` — returns Tier 2 file summary (heading, summary, role, LOC, tokens, symbols list as markdown)
  3. `get_symbol_detail(repo_name, symbol_name)` — returns Tier 3 symbol detail (signature, file:line, summary, parameters, return type, calls)
  4. `search_context(repo_name, query, max_results=10)` — returns ranked markdown table of search results (score, kind, path, name, summary)
  5. `get_repo_status(repo_name)` — returns status as markdown bullet list (indexed commit, current HEAD, staleness, file/symbol counts, total tokens, last indexed)
  6. `sync_repo(repo_name)` — triggers incremental sync and returns change summary or "Already up to date"; raises `NoIndexError` if no prior index
  7. `list_repos()` — returns markdown table of all registered repos (name, remote URL, indexed commit, last indexed)
- All tools return structured markdown strings optimized for LLM consumption
- Error handling: `CodetexError` caught and re-raised as `ValueError`, which FastMCP wraps as `ToolError` with `isError=True` and descriptive messages
- Server uses stdio transport via `server.run()` (called from `codetex serve` CLI command)

### Tests added
- Created `tests/test_server/` directory with `__init__.py` and `test_mcp_server.py`
- 22 tests across 9 test classes:
  - `TestCreateServer` (2 tests) — returns FastMCP with name "codetex", all 7 tools registered
  - `TestGetRepoOverview` (3 tests) — returns overview, no-index raises ToolError, repo-not-found raises ToolError
  - `TestGetFileContext` (2 tests) — returns full file context, file-not-found raises ToolError
  - `TestGetSymbolDetail` (2 tests) — returns full symbol detail, symbol-not-found raises ToolError
  - `TestSearchContext` (3 tests) — returns results table, no results returns message, max_results passed through
  - `TestGetRepoStatus` (3 tests) — normal status, stale detection, not-indexed status
  - `TestSyncRepo` (3 tests) — sync with changes, already-current, no-index raises ToolError
  - `TestListRepos` (2 tests) — repos table, empty list message
  - `TestGetCtx` (2 tests) — creates app on first call, reuses on second call
- mypy passes (36 source files, no issues)
- All 504 tests pass (22 new + 482 existing)

### Notes for next developer
- `_app_ctx` is a module-level global — `_get_ctx()` creates it lazily. The `autouse` fixture in tests resets it to `None` before each test
- FastMCP wraps all exceptions raised in tool functions as `ToolError`. Tests use `pytest.raises(ToolError, match=...)` not `ValueError`
- The error conversion pattern is: `CodetexError` → `ValueError` (in tool function) → `ToolError` (by FastMCP). The `ValueError` message includes the original error message, and `ToolError` message includes the tool name prefix
- Tools access internal FastMCP `_tool_manager` for testing — this is an implementation detail but the only way to unit-test individual tools without running a full MCP session
- The `serve` command in CLI was already wired in US-019 to call `create_server().run()` — this story just added the tools to the server
- **All 20 user stories (US-001 through US-020) are now complete.** The project has full functionality: CLI, MCP server, indexing, syncing, search, and context retrieval

## US-033: Task completion evaluation framework

**Status:** Complete
**Date:** 2026-03-30

### What was done
- Created `src/codetex_mcp/benchmarks/task_metrics.py` with 6 pure metric functions:
  - `exact_match(expected, actual) -> float` — strict equality after whitespace stripping
  - `line_coverage(expected_lines, actual) -> float` — fraction of expected lines found as substrings in actual
  - `symbol_presence(expected_symbols, actual) -> float` — fraction of expected symbol names found (case-sensitive)
  - `keyword_overlap(expected_keywords, actual) -> float` — fraction of expected keywords found (case-insensitive)
  - `aggregate_correctness(symbol_score, keyword_score, line_score) -> float` — weighted aggregate (0.4 symbol + 0.3 keyword + 0.3 line)
  - `success_rate(scores, threshold=0.5) -> float` — fraction of tasks with score >= threshold
- Created `benchmarks/fixtures/codetex_mcp/task_completion_tasks.json` with 10 curated coding tasks:
  - Each task has: id, task description, expected_symbols, expected_keywords, expected_lines, verifiable_answer
  - Tasks cover: sqlite-vec binary serialization, binary file detection, SQLite pragmas, IR metrics, git URL parsing, upsert gotchas, dataclass patterns, rate limiting, language detection, directory tree building
- Created `benchmarks/test_task_completion_bench.py` with benchmark runner:
  - `_score_task(task, actual)` — scores a single task against ground truth using all sub-metrics
  - `_build_codetex_context(repo_path, task)` — builds simulated codetex-style context (signatures + docstrings)
  - `_run_task_completion_benchmark(fixture_file, repo_name, results_dir, with_context)` — full runner with JSON result output
  - `TestTaskCompletionBenchmark` class with `@pytest.mark.benchmark` marker and two tests: baseline and with_context
  - Framework validates scoring pipeline using verifiable_answer as simulated LLM output
- Created `tests/test_benchmarks/test_task_metrics.py` with 38 unit tests across 7 classes:
  - `TestExactMatch` (7 tests) — identical/different/whitespace/case/empty
  - `TestLineCoverage` (6 tests) — all/none/partial/empty/stripped
  - `TestSymbolPresence` (6 tests) — all/none/partial/case/empty
  - `TestKeywordOverlap` (6 tests) — all/none/partial/case-insensitive/empty
  - `TestAggregateCorrectness` (6 tests) — perfect/zero/individual weights/mixed
  - `TestSuccessRate` (7 tests) — all/none/partial/custom threshold/empty/boundary
- mypy passes (42 source files, no issues)
- All 659 tests pass (38 new + 621 existing)
- Benchmark runner passes: `uv run pytest benchmarks/test_task_completion_bench.py -m benchmark -v`

### Notes for next developer
- The benchmark runner currently uses `verifiable_answer` from fixtures as simulated LLM output — this validates the scoring framework without actual API calls
- For real A/B testing (US-035), replace the `actual = task.get("verifiable_answer", "")` line with an actual LLM API call, passing `_build_codetex_context()` output as context for the "with context" condition
- `aggregate_correctness` weights (0.4/0.3/0.3) are a reasonable starting point — adjust based on which dimension is most important for the use case
- Tasks in the fixture don't have `relevant_files` — the `_build_codetex_context` helper gracefully handles this via `.get("relevant_files", [])`. Add `relevant_files` to tasks when you want the context builder to include actual file signatures
- The `success_rate` function treats scores exactly at the threshold as passing (>= not >)
- Next priority: **US-034** (LLM-as-judge scoring system) — requires building scoring prompt templates and calibration methodology
- Architecture reference: `tasks/prd-evaluation.md` §Approach 3
