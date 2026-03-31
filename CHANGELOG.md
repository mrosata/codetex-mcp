# CHANGELOG


## v0.4.0 (2026-03-31)

### Features

- Add evaluation framework with IR metrics, token efficiency benchmarks, and AGENT.md
  ([`8e831fb`](https://github.com/mrosata/codetex-mcp/commit/8e831fbb18c39b0762c9fdc1b78b9506ef8bef05))

Implements approaches 1 (retrieval quality) and 2 (context efficiency) from the evaluation PRD. Adds
  pure-function metric libraries, grep/raw-file baselines, curated ground-truth fixtures for
  codetex-mcp and Flask, pytest benchmark runners that produce structured JSON results, and
  comprehensive AGENT.md documentation.

US-021 through US-032 complete (621 tests, mypy clean, 41 source files).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.0 (2026-03-30)

### Features

- Add pipeline step progress reporting and timeout protection to CLI
  ([`012411b`](https://github.com/mrosata/codetex-mcp/commit/012411b7eb567c50656089be36547989bd53d7db))

Index and sync commands now show which pipeline step is running (e.g. "Generating file summaries (25
  files)...") via animated spinners, so the user always knows the CLI is working. Both commands
  accept a --timeout flag (default 30 min) to prevent indefinite hangs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Index command auto-delegates to incremental sync when already indexed
  ([`10c2fa2`](https://github.com/mrosata/codetex-mcp/commit/10c2fa2b3245d8a702998bd414b4cd929b2de511))

Running `codetex index` on an already-indexed repo now uses the incremental sync pipeline (only
  changed files), avoiding redundant LLM calls and embedding regeneration. Use `--force` to rebuild
  from scratch when needed.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.3 (2026-03-30)

### Bug Fixes

- Format fix
  ([`3d80ca1`](https://github.com/mrosata/codetex-mcp/commit/3d80ca1b165cbd328552ba635a8a490a67c13fc0))

### Testing

- Add regression tests for UPSERT lastrowid bug & re-index FK integrity
  ([`ab91c8f`](https://github.com/mrosata/codetex-mcp/commit/ab91c8faac23ef869e2f0997ac2cb1573288dd7f))

Cover the fixed UPSERT lastrowid behavior (interleaved inserts returning stale IDs), vec0 orphan
  cleanup ordering, re-index/sync FK constraint safety, and FK enforcement after executescript
  migration.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.2 (2026-03-30)

### Bug Fixes

- Always query back file_id after upsert — lastrowid unreliable with UPSERT
  ([`a25f35e`](https://github.com/mrosata/codetex-mcp/commit/a25f35eb63c57982e97e048ad79f460aff1d9ce8))

SQLite documents that last_insert_rowid() is NOT updated when an UPSERT triggers DO UPDATE rather
  than INSERT. The previous code relied on cursor.lastrowid with a fallback only for the value 0,
  but the stale value can be any non-zero rowid from a previous INSERT on a different table (e.g.
  upsert_symbol), causing the indexer to use a non-existent file_id and fail with FOREIGN KEY
  constraint violation.

Fix: upsert_file now always queries back via (repo_id, path) to get the authoritative file_id.
  Removes the broken lastrowid+fallback pattern from both the indexer and syncer.

Ref: https://sqlite.org/c3ref/last_insert_rowid.html "an UPSERT that results in an UPDATE rather
  than an INSERT does not change the last_insert_rowid()"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.1 (2026-03-30)

### Bug Fixes

- Delete vec embeddings before symbols during re-index
  ([`081acdf`](https://github.com/mrosata/codetex-mcp/commit/081acdfc77851eb3a4b4065be183c3cb4a8f5c12))

Vec0 virtual tables don't participate in SQLite FK cascades, so deleting symbols without first
  removing their vec_symbol_embeddings rows left orphaned references that triggered FOREIGN KEY
  constraint failures on subsequent index runs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.0 (2026-03-30)

### Features

- Include all tree-sitter grammars as default dependencies
  ([`55ec9b6`](https://github.com/mrosata/codetex-mcp/commit/55ec9b63752681e7df410305093aaa5834aa35f1))

Move all 8 tree-sitter grammar packages (Python, JS, TS, Go, Rust, Java, Ruby, C/C++) from optional
  extras into main dependencies so they install automatically. Users no longer need separate install
  steps for AST parsing support.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.3 (2026-03-30)

### Bug Fixes

- Add .coverage to .gitignore
  ([`178b3e9`](https://github.com/mrosata/codetex-mcp/commit/178b3e99a9a202accd0932fd8e2105ef4649d939))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.2 (2026-03-30)

### Bug Fixes

- **ci**: Move dev deps to dependency-groups and fix lint/format
  ([`818cb98`](https://github.com/mrosata/codetex-mcp/commit/818cb982a09b251b1834b594c2187f958c703402))

Move dev dependencies (ruff, mypy, pytest) from [project.optional-dependencies] to
  [dependency-groups] so uv sync installs them automatically in CI. Fix ruff lint errors (unused
  imports) and apply ruff format across all source files.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.1 (2026-03-29)

### Bug Fixes

- **ci**: Remove build_command from semantic-release config
  ([`a3dd857`](https://github.com/mrosata/codetex-mcp/commit/a3dd857ae2e6af13b9c5e45d1acec5726f80ecf9))

The PSR GitHub Action runs in a Docker container without uv, causing `uv build` to fail with exit
  code 127. The workflow already has a separate build step that runs on the runner.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.0 (2026-03-29)
