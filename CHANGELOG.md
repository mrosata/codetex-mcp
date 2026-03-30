# CHANGELOG


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
