# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**codetex-mcp** is a commit-aware code context manager for LLMs, providing both an MCP server (stdio transport) and a CLI. It indexes Git repositories into a multi-tier context hierarchy (repo overview → file summaries → symbol details), stores results in SQLite with sqlite-vec for vector search, and serves them to LLM clients via the MCP protocol.

**Status:** Early stage — project scaffolding and detailed architecture/PRD exist, implementation is in progress.

## Development Environment

- **Python:** >=3.12 (see `.python-version`)
- **Package Manager:** uv
- **Linting/Formatting:** ruff
- **Type Checking:** mypy
- **Testing:** pytest with pytest-asyncio

## Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run a single test file
uv run pytest tests/test_storage/test_database.py

# Run tests with coverage
uv run pytest --cov=codetex_mcp

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/

# Run CLI
uv run codetex <command>

# Run as module
uv run python -m codetex_mcp

# Run MCP server (stdio transport)
uv run codetex serve
```

## Architecture

Two entry points (CLI via Typer, MCP server via FastMCP) share the same core service layer. No DI framework — services are wired manually via a `create_app()` factory.

```
CLI (typer) ──┐
              ├──▶ core/ (RepoManager, Indexer, Syncer, ContextStore, SearchEngine)
MCP (FastMCP)─┘        │           │            │
                   analysis/    llm/      embeddings/
                   (tree-sitter + fallback)  (sentence-transformers)
                        └──────────┼────────────┘
                              storage/ (SQLite + sqlite-vec)
                                │
                          git/ ←─┴──▶ config/
```

**Key modules under `src/codetex_mcp/`:**
- `cli/app.py` — Typer app with 8 commands (add, index, sync, context, status, list, serve, config)
- `server/mcp_server.py` — FastMCP server with 7 tools
- `core/` — Domain logic (no direct I/O, dependencies injected)
- `analysis/` — Tree-sitter AST parsing with regex fallback; `parser.py` is the unified dispatcher
- `llm/provider.py` — Abstract base + Anthropic implementation for tier summarization
- `embeddings/embedder.py` — sentence-transformers wrapper (lazy model loading)
- `storage/` — SQLite via aiosqlite; DAO pattern with separate modules per entity (repositories, files, symbols, vectors)
- `storage/migrations/` — SQL migration files applied by `database.py`
- `git/operations.py` — Subprocess git wrapper (no GitPython)
- `config/settings.py` — TOML config loader with env var overrides
- `exceptions.py` — Error hierarchy (11 exception classes)

**Data model:** Single SQLite database for all repos. 6 main tables (repositories, files, symbols, dependencies, repo_overviews, schema_version) + 2 vector tables (384-dim embeddings for files and symbols).

**Pipelines:** Full index is a 9-step pipeline (discover files → parse AST → generate summaries → embed → store). Incremental sync is a 7-step pipeline using git diff to process only changed files.

## Reference Documents

- `tasks/architecture.md` — Complete technical architecture (module interfaces, data model, pipeline specs, config schema, wiring)
- `tasks/prd-code-context-manager.md` — Product requirements document
- `prd.json` — PRD in structured JSON with 20 user stories and acceptance criteria

## Conventions

- All core services are async
- Tree-sitter grammars for all 8 supported languages are included as default dependencies
- Config lives at `~/.codetex/config.toml` at runtime; SQLite database at `~/.codetex/codetex.db`
- MCP tool responses are structured markdown strings optimized for LLM consumption
- CLI output uses `rich` for progress bars, tables, and markdown rendering
