# Architecture: codetex-mcp

> Commit-aware code context manager for LLMs — MCP server and CLI

This document defines the internal structure, data model, component interfaces, and key design decisions for codetex-mcp. It translates the [PRD](./prd-code-context-manager.md) into a buildable system design. The next document in sequence is the **Implementation Plan**, which breaks this architecture into ordered development tasks.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Project Directory Structure](#2-project-directory-structure)
3. [Module Architecture](#3-module-architecture)
4. [Data Model](#4-data-model)
5. [Pipelines](#5-pipelines)
6. [MCP Tool Signatures](#6-mcp-tool-signatures)
7. [CLI Commands](#7-cli-commands)
8. [Configuration Schema](#8-configuration-schema)
9. [Error Handling](#9-error-handling)
10. [Application Bootstrap & Wiring](#10-application-bootstrap--wiring)
11. [Dependencies](#11-dependencies)
12. [Design Decisions](#12-design-decisions)
13. [Future Extensibility](#13-future-extensibility)
14. [FR Traceability Matrix](#14-fr-traceability-matrix)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        User / LLM Client                        │
│                                                                  │
│   CLI (typer)              MCP Client (Claude Code, etc.)        │
│       │                           │                              │
│       ▼                           ▼                              │
│  ┌─────────┐              ┌──────────────┐                       │
│  │  cli/   │              │   server/    │  (stdio transport)    │
│  └────┬────┘              └──────┬───────┘                       │
│       │                          │                               │
│       └──────────┬───────────────┘                               │
│                  ▼                                                │
│          ┌──────────────┐                                        │
│          │    core/     │  RepoManager · Indexer · Syncer        │
│          │              │  ContextStore · SearchEngine            │
│          └──┬───┬───┬───┘                                        │
│             │   │   │                                            │
│      ┌──────┘   │   └──────┐                                     │
│      ▼          ▼          ▼                                     │
│ ┌──────────┐ ┌────────┐ ┌────────────┐                          │
│ │analysis/ │ │  llm/  │ │embeddings/ │                          │
│ └──────────┘ └────────┘ └────────────┘                          │
│      │          │            │                                   │
│      └──────────┼────────────┘                                   │
│                 ▼                                                 │
│          ┌──────────────┐                                        │
│          │   storage/   │  SQLite + sqlite-vec                   │
│          └──────────────┘                                        │
│                 │                                                 │
│          ┌──────┴──────┐                                         │
│          ▼             ▼                                         │
│     ┌────────┐   ┌──────────┐                                    │
│     │  git/  │   │  config/ │                                    │
│     └────────┘   └──────────┘                                    │
└──────────────────────────────────────────────────────────────────┘
```

**Data flow:** User invokes a command (CLI) or an LLM calls a tool (MCP). Both routes resolve to the same core service methods. Core services orchestrate analysis, LLM summarization, embedding, and storage. Git operations and configuration are cross-cutting concerns used by multiple layers.

---

## 2. Project Directory Structure

```
codetex-mcp/
├── pyproject.toml
├── README.md
├── tasks/
│   ├── prd-code-context-manager.md
│   ├── architecture.md              ← this file
│   └── implementation-plan.md       ← next document
├── src/
│   └── codetex_mcp/
│       ├── __init__.py              # Package version, public API
│       ├── __main__.py              # `python -m codetex_mcp` entry point
│       ├── cli/
│       │   ├── __init__.py
│       │   └── app.py               # Typer application, all commands
│       ├── server/
│       │   ├── __init__.py
│       │   └── mcp_server.py        # FastMCP server, 7 tools
│       ├── core/
│       │   ├── __init__.py
│       │   ├── repo_manager.py      # Clone, register, list repos
│       │   ├── indexer.py           # Full index pipeline
│       │   ├── syncer.py            # Incremental sync pipeline
│       │   ├── context_store.py     # Read/query indexed context
│       │   └── search_engine.py     # Semantic search over embeddings
│       ├── analysis/
│       │   ├── __init__.py
│       │   ├── tree_sitter.py       # Tree-sitter AST parser
│       │   ├── fallback_parser.py   # Line-based regex extraction
│       │   ├── parser.py            # Unified parser interface (dispatcher)
│       │   └── models.py            # FileAnalysis, SymbolInfo dataclasses
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── provider.py          # Abstract base + Anthropic impl
│       │   ├── prompts.py           # Prompt templates for Tiers 1/2/3
│       │   └── rate_limiter.py      # Async semaphore + exponential backoff
│       ├── embeddings/
│       │   ├── __init__.py
│       │   └── embedder.py          # sentence-transformers wrapper
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── database.py          # Connection management, migrations
│       │   ├── repositories.py      # Repository CRUD
│       │   ├── files.py             # File records CRUD
│       │   ├── symbols.py           # Symbol records CRUD
│       │   ├── vectors.py           # sqlite-vec insert/query
│       │   └── migrations/
│       │       └── 001_initial.sql  # Initial schema
│       ├── git/
│       │   ├── __init__.py
│       │   └── operations.py        # Subprocess git wrapper
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py          # Config dataclass, TOML loader, env overrides
│       │   └── ignore.py            # .gitignore + .codetexignore filter
│       └── exceptions.py            # Error hierarchy
└── tests/
    ├── conftest.py
    ├── test_cli/
    ├── test_core/
    ├── test_analysis/
    ├── test_llm/
    ├── test_embeddings/
    ├── test_storage/
    ├── test_git/
    └── test_config/
```

---

## 3. Module Architecture

### 3.1 `cli/` — Command-Line Interface

**Framework:** Typer (builds on Click, provides type-hint-driven CLI generation)

**File:** `cli/app.py`

The CLI is a thin dispatch layer. Each command validates arguments, instantiates or retrieves the wired service graph (see §10), calls a core service method, and formats the result for terminal output.

```python
# Public interface
app = typer.Typer(name="codetex")

@app.command()
def add(target: str) -> None: ...

@app.command()
def index(repo_name: str, path: Optional[str], dry_run: bool) -> None: ...

@app.command()
def sync(repo_name: str, path: Optional[str], dry_run: bool) -> None: ...

@app.command()
def context(repo_name: str, file: Optional[str], symbol: Optional[str], query: Optional[str]) -> None: ...

@app.command()
def status(repo_name: str) -> None: ...

@app.command()
def list() -> None: ...

@app.command()
def serve() -> None: ...

@app.command()
def config(action: str, key: Optional[str], value: Optional[str]) -> None: ...
```

**Output formatting:** Uses `rich` for terminal markdown rendering, progress bars during indexing, and status tables.

---

### 3.2 `server/` — MCP Server

**Framework:** FastMCP from the `mcp` Python SDK

**Transport:** stdio (launched as a subprocess by the MCP client)

**File:** `server/mcp_server.py`

The MCP server exposes 7 tools. Each tool is a thin async wrapper that calls the same core services as the CLI.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codetex")

@mcp.tool()
async def get_repo_overview(repo_name: str) -> str: ...

@mcp.tool()
async def get_file_context(repo_name: str, file_path: str) -> str: ...

@mcp.tool()
async def get_symbol_detail(repo_name: str, symbol_name: str) -> str: ...

@mcp.tool()
async def search_context(repo_name: str, query: str, max_results: int = 10) -> str: ...

@mcp.tool()
async def get_repo_status(repo_name: str) -> str: ...

@mcp.tool()
async def sync_repo(repo_name: str) -> str: ...

@mcp.tool()
async def list_repos() -> str: ...
```

Tool responses are returned as structured markdown strings optimized for LLM consumption.

---

### 3.3 `core/` — Business Logic

The core module contains all domain logic. No direct I/O — all external concerns (storage, git, LLM, embeddings) are injected as dependencies.

#### 3.3.1 `RepoManager`

Manages repository lifecycle: clone, register local, list, remove.

```python
class RepoManager:
    def __init__(self, db: Database, git: GitOperations, config: Settings): ...

    async def add_remote(self, url: str) -> Repository: ...
    async def add_local(self, path: Path) -> Repository: ...
    async def list_repos(self) -> list[Repository]: ...
    async def get_repo(self, name: str) -> Repository: ...
    async def remove_repo(self, name: str) -> None: ...
```

**`add` dispatch logic:** If `target` looks like a URL (contains `://` or starts with `git@`), call `add_remote`. If it's a local path, call `add_local`. The repo name is derived from the URL/path basename (minus `.git` suffix).

#### 3.3.2 `Indexer`

Orchestrates the full indexing pipeline (see §5.1).

```python
class Indexer:
    def __init__(
        self,
        db: Database,
        git: GitOperations,
        parser: Parser,
        llm: LLMProvider,
        embedder: Embedder,
        config: Settings,
    ): ...

    async def index(
        self,
        repo: Repository,
        path_filter: str | None = None,
        dry_run: bool = False,
    ) -> IndexResult: ...
```

**`IndexResult`** dataclass returned on completion:
```python
@dataclass
class IndexResult:
    files_indexed: int
    symbols_extracted: int
    llm_calls_made: int
    tokens_used: int
    duration_seconds: float
    commit_sha: str
```

**Dry-run mode:** Runs file discovery and static analysis only. Returns estimated LLM calls and token counts without making any API requests.

**Progress reporting:** Accepts an optional callback `on_progress(current: int, total: int, file: str)` used by the CLI to render a progress bar.

#### 3.3.3 `Syncer`

Orchestrates the incremental sync pipeline (see §5.2).

```python
class Syncer:
    def __init__(
        self,
        db: Database,
        git: GitOperations,
        parser: Parser,
        llm: LLMProvider,
        embedder: Embedder,
        config: Settings,
    ): ...

    async def sync(
        self,
        repo: Repository,
        path_filter: str | None = None,
        dry_run: bool = False,
    ) -> SyncResult: ...
```

**`SyncResult`** dataclass:
```python
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
```

#### 3.3.4 `ContextStore`

Reads indexed context from the database. No writes — this is the read path.

```python
class ContextStore:
    def __init__(self, db: Database): ...

    async def get_repo_overview(self, repo_id: int) -> str | None: ...
    async def get_file_context(self, repo_id: int, file_path: str) -> FileContext | None: ...
    async def get_symbol_detail(self, repo_id: int, symbol_name: str) -> SymbolDetail | None: ...
    async def get_repo_status(self, repo_id: int) -> RepoStatus: ...
```

#### 3.3.5 `SearchEngine`

Handles semantic search over vector embeddings.

```python
class SearchEngine:
    def __init__(self, db: Database, embedder: Embedder): ...

    async def search(
        self,
        repo_id: int,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]: ...
```

**`SearchResult`** dataclass:
```python
@dataclass
class SearchResult:
    kind: Literal["file", "symbol"]
    path: str
    name: str
    summary: str
    score: float
```

**Search algorithm:**
1. Embed the query string using the same model as index-time embeddings.
2. Run a nearest-neighbor query against `vec_file_embeddings` and `vec_symbol_embeddings` using sqlite-vec's `vec_distance_cosine`.
3. Merge and rank results by cosine similarity score.
4. Return top-N results with their summaries.

---

### 3.4 `analysis/` — Static Analysis

#### 3.4.1 `Parser` (dispatcher)

```python
class Parser:
    def __init__(self, tree_sitter_parser: TreeSitterParser, fallback: FallbackParser): ...

    def parse_file(self, path: Path, content: str, language: str | None = None) -> FileAnalysis: ...
    def detect_language(self, path: Path) -> str | None: ...
```

Detects language from file extension, delegates to tree-sitter if a grammar is available, otherwise falls back to line-based extraction.

#### 3.4.2 `TreeSitterParser`

```python
class TreeSitterParser:
    def __init__(self): ...

    def is_language_supported(self, language: str) -> bool: ...
    def parse(self, content: str, language: str) -> FileAnalysis: ...
```

**Grammar loading:** Grammars are installed as optional pip extras (`tree-sitter-python`, `tree-sitter-javascript`, etc.). On first call for a language, attempt to load the grammar. If unavailable, report that language as unsupported so the dispatcher can fall back.

**Extracted data:**
- Function/method signatures (name, parameters, return type annotation)
- Class definitions (name, bases, methods)
- Import statements (module, imported names)
- Export list (for languages with explicit exports)
- Docstrings / leading comments

#### 3.4.3 `FallbackParser`

Line-based regex extraction for languages without tree-sitter support.

```python
class FallbackParser:
    def parse(self, content: str, language: str | None) -> FileAnalysis: ...
```

Extracts:
- Lines matching common function/class patterns (`def`, `function`, `class`, `func`, `fn`, etc.)
- Import/require/include lines
- File-level comments / docstrings (first contiguous comment block)

#### 3.4.4 Data Models

```python
@dataclass
class FileAnalysis:
    """Result of parsing a single source file."""
    path: str
    language: str | None
    imports: list[ImportInfo]
    symbols: list[SymbolInfo]
    lines_of_code: int
    token_count: int          # Exact token count via tiktoken

@dataclass
class ImportInfo:
    module: str
    names: list[str]          # Specific imported names, or empty for wildcard

@dataclass
class SymbolInfo:
    name: str
    kind: Literal["function", "method", "class", "variable", "constant"]
    signature: str            # Full signature string
    docstring: str | None
    start_line: int
    end_line: int
    parameters: list[ParameterInfo]
    return_type: str | None
    calls: list[str]          # Names of functions/methods called within this symbol

@dataclass
class ParameterInfo:
    name: str
    type_annotation: str | None
    default_value: str | None
```

---

### 3.5 `llm/` — LLM Integration

#### 3.5.1 `LLMProvider` (abstract base + Anthropic implementation)

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    async def summarize(self, prompt: str, system: str | None = None) -> str: ...

    @abstractmethod
    async def summarize_batch(self, prompts: list[str], system: str | None = None) -> list[str]: ...

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"): ...

    async def summarize(self, prompt: str, system: str | None = None) -> str: ...
    async def summarize_batch(self, prompts: list[str], system: str | None = None) -> list[str]: ...
```

`summarize_batch` sends concurrent requests up to `max_concurrent_llm_calls`, coordinated by the rate limiter.

#### 3.5.2 `prompts.py` — Prompt Templates

Three template functions, one per tier:

```python
def tier1_prompt(repo_name: str, directory_tree: str, file_summaries: list[str], technologies: list[str]) -> str: ...
def tier2_prompt(file_path: str, content: str, symbols: list[SymbolInfo]) -> str: ...
def tier3_prompt(symbol: SymbolInfo, file_context: str) -> str: ...
```

Each returns a fully rendered prompt string. Templates use f-strings with clear structure to maximize LLM comprehension. System prompts instruct the LLM to respond in a specific markdown format for consistent parsing.

#### 3.5.3 `RateLimiter`

```python
class RateLimiter:
    def __init__(self, max_concurrent: int = 5, base_delay: float = 1.0, max_delay: float = 60.0): ...

    async def acquire(self) -> None: ...
    async def release(self) -> None: ...
    async def handle_rate_limit(self) -> None: ...  # Exponential backoff
```

Wraps `asyncio.Semaphore` for concurrency limiting. On 429/rate-limit errors, applies exponential backoff with jitter before retrying.

---

### 3.6 `embeddings/` — Vector Embeddings

```python
class Embedder:
    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMENSIONS = 384

    def __init__(self): ...

    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

**Lazy loading:** The `sentence-transformers` model is downloaded and loaded on the first call to `embed` or `embed_batch`. This avoids startup cost when the user hasn't indexed anything yet.

**Model details:**
- `all-MiniLM-L6-v2`: 384-dimension vectors, ~23MB download, CPU-only
- Produces normalized vectors suitable for cosine similarity

**Embedding strategy:**
- **File embeddings:** Embed the concatenation of `"{file_path}: {tier2_summary}"`
- **Symbol embeddings:** Embed the concatenation of `"{symbol_name} ({kind}): {tier3_summary}"`

---

### 3.7 `storage/` — Database Layer

#### 3.7.1 `Database`

```python
class Database:
    def __init__(self, db_path: Path): ...

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor: ...
    async def executemany(self, sql: str, params: list[tuple]) -> None: ...
    async def migrate(self) -> None: ...
```

**Connection management:** Uses `aiosqlite` for async access. Single connection per process with WAL mode enabled for concurrent reads.

**Migrations:** Numbered SQL files in `storage/migrations/`. On startup, the `schema_version` table tracks which migrations have been applied. New migrations are applied in order.

**sqlite-vec:** Loaded as an extension on connection open via `db.enable_load_extension(True)` and `db.load_extension("vec0")`.

#### 3.7.2 Repository-specific DAOs

Each DAO module (`repositories.py`, `files.py`, `symbols.py`, `vectors.py`) provides CRUD functions scoped to a single concern. They accept a `Database` instance and return domain dataclasses.

---

### 3.8 `git/` — Git Operations

```python
class GitOperations:
    def __init__(self, config: Settings): ...

    async def clone(self, url: str, target_dir: Path) -> None: ...
    async def get_head_commit(self, repo_path: Path) -> str: ...
    async def get_default_branch(self, repo_path: Path) -> str: ...
    async def get_remote_url(self, repo_path: Path) -> str | None: ...
    async def diff_commits(self, repo_path: Path, from_sha: str, to_sha: str) -> DiffResult: ...
    async def list_tracked_files(self, repo_path: Path) -> list[str]: ...
    async def is_git_repo(self, path: Path) -> bool: ...
```

**Implementation:** All operations use `asyncio.create_subprocess_exec` to call the `git` binary. This avoids the weight of `gitpython` and delegates authentication entirely to the user's git/SSH config.

**`DiffResult`** dataclass:
```python
@dataclass
class DiffResult:
    added: list[str]       # New file paths
    modified: list[str]    # Changed file paths
    deleted: list[str]     # Removed file paths
    renamed: list[tuple[str, str]]  # (old_path, new_path)
```

---

### 3.9 `config/` — Configuration

#### 3.9.1 `Settings`

```python
@dataclass
class Settings:
    # Storage
    data_dir: Path = Path.home() / ".codetex"
    repos_dir: Path = data_dir / "repos"
    db_path: Path = data_dir / "codetex.db"

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5-20250929"
    llm_api_key: str | None = None                  # Env: ANTHROPIC_API_KEY

    # Indexing
    max_file_size_kb: int = 512
    max_concurrent_llm_calls: int = 5
    tier1_rebuild_threshold: float = 0.10           # 10% of files
    default_excludes: list[str] = field(default_factory=lambda: [
        "node_modules/", "vendor/", "__pycache__/", ".git/",
        "*.min.js", "*.min.css", "*.lock", "*.map",
        "*.pyc", "*.pyo", "*.so", "*.dylib",
        "dist/", "build/", ".tox/", ".venv/", "venv/",
    ])

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"

    @classmethod
    def load(cls) -> "Settings": ...
```

**Load order (last wins):**
1. Hardcoded defaults (in the dataclass)
2. `~/.codetex/config.toml` (user config file)
3. Environment variables (prefixed `CODETEX_`, e.g. `CODETEX_LLM_API_KEY`)

**TOML schema:**

```toml
[storage]
data_dir = "~/.codetex"

[llm]
provider = "anthropic"
model = "claude-sonnet-4-5-20250929"
api_key = ""                        # Or use ANTHROPIC_API_KEY env var

[indexing]
max_file_size_kb = 512
max_concurrent_llm_calls = 5
tier1_rebuild_threshold = 0.10
exclude_patterns = [
    "node_modules/", "vendor/", "__pycache__/",
    "*.min.js", "*.lock", "*.map",
]

[embedding]
model = "all-MiniLM-L6-v2"
```

#### 3.9.2 `IgnoreFilter`

```python
class IgnoreFilter:
    def __init__(self, repo_path: Path, default_excludes: list[str]): ...

    def is_excluded(self, file_path: Path) -> tuple[bool, str | None]: ...
    def filter_files(self, files: list[str]) -> list[str]: ...
```

**Filter chain (in order):**
1. Default excludes from config
2. `.gitignore` rules (via `pathspec` library)
3. `.codetexignore` rules (same syntax, can override with `!pattern`)
4. Max file size check
5. Binary file detection (null byte check in first 8KB)

`is_excluded` returns `(True, reason)` or `(False, None)` — the reason string is used in `--dry-run` output to explain why a file was skipped.

---

### 3.10 `exceptions.py` — Error Hierarchy

```python
class CodetexError(Exception):
    """Base exception. All codetex errors inherit from this."""
    pass

class RepositoryNotFoundError(CodetexError):
    """Repo name doesn't match any registered repository."""
    pass

class RepositoryAlreadyExistsError(CodetexError):
    """Attempting to add a repo that's already registered."""
    pass

class GitError(CodetexError):
    """Wraps git subprocess failures with actionable context."""
    pass

class GitAuthError(GitError):
    """Authentication failed — includes setup guidance."""
    def __init__(self, url: str):
        super().__init__(
            f"Authentication failed for '{url}'. "
            "Ensure SSH keys are configured (git@...) or a credential helper "
            "is set up for HTTPS. See: https://git-scm.com/doc/credential-helpers"
        )

class IndexError(CodetexError):
    """Error during indexing pipeline."""
    pass

class LLMError(CodetexError):
    """LLM API call failed."""
    pass

class RateLimitError(LLMError):
    """Rate limit hit — handled by automatic retry with backoff."""
    pass

class ConfigError(CodetexError):
    """Invalid configuration value."""
    pass

class DatabaseError(CodetexError):
    """Database corruption or migration failure."""
    pass

class EmbeddingError(CodetexError):
    """Embedding model load or inference failure."""
    pass

class NoIndexError(CodetexError):
    """Repo exists but has no index — user needs to run `codetex index` first."""
    pass
```

---

## 4. Data Model

### 4.1 SQLite Schema

All tables live in a single database file: `~/.codetex/codetex.db`. Multi-repo is supported from day one via `repo_id` foreign keys.

#### `schema_version`
```sql
CREATE TABLE schema_version (
    version   INTEGER PRIMARY KEY,
    applied   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

#### `repositories`
```sql
CREATE TABLE repositories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    remote_url      TEXT,
    local_path      TEXT NOT NULL,
    default_branch  TEXT NOT NULL DEFAULT 'main',
    indexed_commit  TEXT,               -- NULL until first index
    last_indexed_at TEXT,               -- ISO 8601 timestamp
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

#### `files`
```sql
CREATE TABLE files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    language        TEXT,
    lines_of_code   INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER NOT NULL DEFAULT 0,
    role            TEXT,               -- 'model', 'controller', 'utility', 'config', 'test', etc.
    summary         TEXT,               -- Tier 2 LLM-generated summary
    imports_json    TEXT,               -- JSON array of import info
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_id, path)
);

CREATE INDEX idx_files_repo ON files(repo_id);
CREATE INDEX idx_files_repo_path ON files(repo_id, path);
```

#### `symbols`
```sql
CREATE TABLE symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,       -- 'function', 'method', 'class', 'variable', 'constant'
    signature       TEXT NOT NULL,
    docstring       TEXT,
    summary         TEXT,               -- Tier 3 LLM-generated summary
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    parameters_json TEXT,               -- JSON array of ParameterInfo
    return_type     TEXT,
    calls_json      TEXT,               -- JSON array of called function names
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_symbols_file ON symbols(file_id);
CREATE INDEX idx_symbols_repo ON symbols(repo_id);
CREATE INDEX idx_symbols_name ON symbols(repo_id, name);
```

#### `dependencies`
```sql
CREATE TABLE dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    source_file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target_path     TEXT NOT NULL,       -- Resolved import path (may be external)
    imported_names  TEXT,               -- JSON array of imported names
    UNIQUE(source_file_id, target_path)
);

CREATE INDEX idx_deps_repo ON dependencies(repo_id);
CREATE INDEX idx_deps_source ON dependencies(source_file_id);
```

#### `repo_overviews`
```sql
CREATE TABLE repo_overviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    overview        TEXT NOT NULL,       -- Tier 1 markdown summary
    directory_tree  TEXT,               -- Stored tree structure
    technologies    TEXT,               -- JSON array of detected tech
    commit_sha      TEXT NOT NULL,       -- Commit this overview was generated for
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_id)                     -- One active overview per repo
);
```

### 4.2 sqlite-vec Virtual Tables

```sql
CREATE VIRTUAL TABLE vec_file_embeddings USING vec0(
    file_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);

CREATE VIRTUAL TABLE vec_symbol_embeddings USING vec0(
    symbol_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
```

**Vector dimensions:** 384 (matches `all-MiniLM-L6-v2` output).

**Query pattern:**
```sql
SELECT file_id, distance
FROM vec_file_embeddings
WHERE embedding MATCH ?
ORDER BY distance
LIMIT ?;
```

---

## 5. Pipelines

### 5.1 Full Index Pipeline

Triggered by `codetex index <repo-name>` or MCP tool (implicitly via sync on first run).

```
Step 1: Discover Files
  ├─ git ls-files → tracked file list
  ├─ Apply IgnoreFilter chain (.gitignore, .codetexignore, defaults, size, binary)
  ├─ Apply --path filter if provided
  └─ Output: list[str] of file paths to index

Step 2: Parse ASTs (parallel, CPU-bound)
  ├─ For each file: detect language → dispatch to TreeSitter or FallbackParser
  ├─ Extract symbols, imports, line counts
  ├─ Compute token count via tiktoken
  └─ Output: list[FileAnalysis]

Step 3: Store Structure
  ├─ Upsert file records (path, language, LOC, token_count, imports_json)
  ├─ Upsert symbol records (name, kind, signature, parameters, calls)
  ├─ Upsert dependency records (source → target)
  └─ Commit per file batch (interrupt-resumable)

Step 4: LLM Summarize — Tier 2 (concurrent, I/O-bound)
  ├─ For each file: render tier2_prompt(file_path, content, symbols)
  ├─ Send to LLM via rate-limited batch
  └─ Output: file_path → summary mapping

Step 5: Store Tier 2 Summaries
  ├─ Update file records with summary and role classification
  └─ Commit per batch

Step 6: LLM Summarize — Tier 3 (concurrent, I/O-bound)
  ├─ For key symbols (functions, classes — skip trivial accessors):
  │   render tier3_prompt(symbol, file_context)
  ├─ Send to LLM via rate-limited batch
  └─ Output: symbol_id → summary mapping

Step 7: Store Tier 3 Summaries
  ├─ Update symbol records with summaries
  └─ Commit per batch

Step 8: Generate Embeddings (CPU-bound, batched)
  ├─ Embed file summaries → vec_file_embeddings
  ├─ Embed symbol summaries → vec_symbol_embeddings
  └─ Commit

Step 9: Generate Tier 1 Overview
  ├─ Render tier1_prompt(repo_name, directory_tree, file_summaries, technologies)
  ├─ Send to LLM (single call)
  ├─ Store in repo_overviews
  ├─ Update repositories.indexed_commit = current HEAD
  └─ Update repositories.last_indexed_at = now
```

**Interrupt-resumability:** Steps 3-7 commit progress per file/batch. If interrupted, re-running `index` detects which files already have entries and skips them (via `updated_at` check against the current indexing session).

### 5.2 Sync Pipeline

Triggered by `codetex sync <repo-name>` or MCP `sync_repo` tool.

```
Step 1: Compare Commits
  ├─ Read repositories.indexed_commit
  ├─ Get current HEAD via git rev-parse
  ├─ If equal → return "already up to date"
  └─ Output: old_sha, new_sha

Step 2: Compute Diff
  ├─ git diff --name-status old_sha..new_sha
  ├─ Apply IgnoreFilter + --path filter
  └─ Output: DiffResult (added, modified, deleted, renamed)

Step 3: Delete Removed
  ├─ For deleted files: remove file, symbol, dependency, and vector records
  └─ Subtract deleted file token counts from totals

Step 4: Re-analyze Changed (same as index Steps 2-7 but scoped)
  ├─ Parse ASTs for added + modified files
  ├─ Store structure
  ├─ LLM summarize Tier 2 for added + modified
  ├─ LLM summarize Tier 3 for new/changed symbols
  └─ Update token counts for changed files

Step 5: Update Embeddings
  ├─ Re-embed changed file summaries
  ├─ Re-embed changed symbol summaries
  ├─ Remove vectors for deleted files/symbols
  └─ Commit

Step 6: Conditional Tier 1 Rebuild
  ├─ changed_ratio = (added + modified + deleted) / total_files
  ├─ If changed_ratio >= tier1_rebuild_threshold:
  │     regenerate Tier 1 overview (same as index Step 9)
  └─ Else: keep existing overview

Step 7: Update Commit
  ├─ repositories.indexed_commit = new_sha
  └─ repositories.last_indexed_at = now
```

---

## 6. MCP Tool Signatures

### 6.1 `get_repo_overview`

```
Input:  { repo_name: string }
Output: Tier 1 markdown overview including:
        - Repository purpose and description
        - Directory structure
        - Key technologies and frameworks
        - Entry points
        - Architecture patterns
Error:  RepositoryNotFoundError | NoIndexError
```

### 6.2 `get_file_context`

```
Input:  { repo_name: string, file_path: string }
Output: Tier 2 file summary including:
        - File purpose (one paragraph)
        - Public interface list
        - Dependencies (imports)
        - Role classification
        - Line count and token count
Error:  RepositoryNotFoundError | FileNotFoundError
```

### 6.3 `get_symbol_detail`

```
Input:  { repo_name: string, symbol_name: string }
Output: Tier 3 symbol detail including:
        - Full signature
        - Description/summary
        - Parameters with types
        - Return type
        - Internal call relationships
        - File location (path:line)
Error:  RepositoryNotFoundError | SymbolNotFoundError
```

### 6.4 `search_context`

```
Input:  { repo_name: string, query: string, max_results?: int (default 10) }
Output: Ranked list of relevant context snippets:
        - Each result: kind (file|symbol), path, name, summary, relevance score
Error:  RepositoryNotFoundError | NoIndexError
```

### 6.5 `get_repo_status`

```
Input:  { repo_name: string }
Output: Status object:
        - indexed_commit: string
        - current_head: string
        - is_stale: boolean
        - files_indexed: int
        - symbols_indexed: int
        - total_tokens: int
        - last_indexed_at: string (ISO 8601)
Error:  RepositoryNotFoundError
```

### 6.6 `sync_repo`

```
Input:  { repo_name: string }
Output: Sync summary:
        - already_current: boolean
        - files_added/modified/deleted: int
        - tier1_rebuilt: boolean
        - old_commit → new_commit
Error:  RepositoryNotFoundError | NoIndexError | LLMError | GitError
```

### 6.7 `list_repos`

```
Input:  {}
Output: Array of registered repositories:
        - Each: name, remote_url, indexed_commit, is_stale, files_indexed
Error:  (none — returns empty list if no repos)
```

---

## 7. CLI Commands

| Command | Maps to | Description |
|---|---|---|
| `codetex add <target>` | `RepoManager.add_remote` / `add_local` | Clone/register a repo |
| `codetex list` | `RepoManager.list_repos` | Show all registered repos |
| `codetex index <repo> [--path P] [--dry-run]` | `Indexer.index` | Full index build |
| `codetex sync <repo> [--path P] [--dry-run]` | `Syncer.sync` | Incremental sync |
| `codetex context <repo> [--file F] [--symbol S] [--query Q]` | `ContextStore` / `SearchEngine` | Query indexed context |
| `codetex status <repo>` | `ContextStore.get_repo_status` | Show index status |
| `codetex serve` | `mcp.run()` | Start MCP server (stdio) |
| `codetex config show` | `Settings.load` | Display current config |
| `codetex config set <key> <value>` | Write to `config.toml` | Update a config value |

**Entry points in `pyproject.toml`:**

```toml
[project.scripts]
codetex = "codetex_mcp.cli.app:main"
```

The `main` function creates the Typer app and calls `app()`.

**`__main__.py`** enables `python -m codetex_mcp`:
```python
from codetex_mcp.cli.app import main
main()
```

---

## 8. Configuration Schema

### 8.1 Full Schema with Defaults

| Key | Type | Default | Env Override | Description |
|---|---|---|---|---|
| `storage.data_dir` | path | `~/.codetex` | `CODETEX_DATA_DIR` | Root for all codetex data |
| `llm.provider` | string | `"anthropic"` | `CODETEX_LLM_PROVIDER` | LLM provider name |
| `llm.model` | string | `"claude-sonnet-4-5-20250929"` | `CODETEX_LLM_MODEL` | Model for summarization |
| `llm.api_key` | string | `null` | `ANTHROPIC_API_KEY` | API key (required for indexing) |
| `indexing.max_file_size_kb` | int | `512` | `CODETEX_MAX_FILE_SIZE_KB` | Skip files larger than this |
| `indexing.max_concurrent_llm_calls` | int | `5` | `CODETEX_MAX_CONCURRENT_LLM` | Parallel LLM call limit |
| `indexing.tier1_rebuild_threshold` | float | `0.10` | `CODETEX_TIER1_THRESHOLD` | Fraction of files triggering Tier 1 rebuild |
| `indexing.exclude_patterns` | list[str] | *(see §3.9)* | — | Additional exclude patterns |
| `embedding.model` | string | `"all-MiniLM-L6-v2"` | `CODETEX_EMBEDDING_MODEL` | Embedding model name |

### 8.2 Minimal Config (only API key needed)

```toml
[llm]
api_key = "sk-ant-..."
```

Everything else uses sensible defaults. The API key can also be set via `ANTHROPIC_API_KEY` environment variable, making a config file entirely optional.

---

## 9. Error Handling

### 9.1 Strategy by Error Category

| Category | Detection | Recovery | User Message |
|---|---|---|---|
| **Git auth failure** | Non-zero exit + "Permission denied" / "Authentication failed" in stderr | Raise `GitAuthError` with setup guidance | Lists SSH and credential helper options |
| **Git clone failure** | Non-zero exit code from `git clone` | Raise `GitError` with stderr content | Shows raw git error + "Is the URL correct?" |
| **LLM rate limit** | HTTP 429 or `RateLimitError` from SDK | Exponential backoff (1s → 2s → 4s ... → 60s max), up to 5 retries | Progress bar pauses, resumes on success |
| **LLM API error** | HTTP 5xx or network error | Retry up to 3 times with backoff, then fail the file/symbol | "Failed to summarize {path}, skipping. Re-run index to retry." |
| **LLM auth failure** | HTTP 401 | Raise `LLMError` immediately (no retry) | "API key invalid. Set via config or ANTHROPIC_API_KEY env var." |
| **Indexing interrupt** | `KeyboardInterrupt` / `asyncio.CancelledError` | Commit partial progress, exit gracefully | "Indexing interrupted. {N} files completed. Re-run to continue." |
| **Database corruption** | `sqlite3.DatabaseError` | Raise `DatabaseError` | "Database may be corrupted. Back up and delete ~/.codetex/codetex.db to reset." |
| **Embedding model download** | Network error during first-use download | Raise `EmbeddingError` | "Failed to download embedding model. Check internet connection." |
| **Binary/oversized file** | Null byte or size > threshold | Skip file, log reason | Shown in `--dry-run` output |
| **Missing tree-sitter grammar** | `ImportError` on grammar load | Fall back to `FallbackParser` | Logged at debug level |

### 9.2 CLI Error Display

All `CodetexError` subclasses are caught at the CLI top level and rendered as:

```
Error: <error message>
```

With a non-zero exit code. Unexpected exceptions show a full traceback with a prompt to file an issue.

### 9.3 MCP Error Display

MCP tool errors return structured error responses per the MCP spec. The `isError` flag is set and the content contains the error message.

---

## 10. Application Bootstrap & Wiring

No dependency injection framework. A single factory function builds the object graph at startup.

```python
# src/codetex_mcp/core/__init__.py

@dataclass
class AppContext:
    settings: Settings
    db: Database
    git: GitOperations
    parser: Parser
    llm: LLMProvider
    embedder: Embedder
    repo_manager: RepoManager
    indexer: Indexer
    syncer: Syncer
    context_store: ContextStore
    search_engine: SearchEngine


async def create_app(settings: Settings | None = None) -> AppContext:
    """Wire the full application object graph."""
    settings = settings or Settings.load()

    db = Database(settings.db_path)
    await db.connect()
    await db.migrate()

    git = GitOperations(settings)

    tree_sitter = TreeSitterParser()
    fallback = FallbackParser()
    parser = Parser(tree_sitter, fallback)

    llm = AnthropicProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    embedder = Embedder()

    repo_manager = RepoManager(db, git, settings)
    context_store = ContextStore(db)
    search_engine = SearchEngine(db, embedder)
    indexer = Indexer(db, git, parser, llm, embedder, settings)
    syncer = Syncer(db, git, parser, llm, embedder, settings)

    return AppContext(
        settings=settings,
        db=db,
        git=git,
        parser=parser,
        llm=llm,
        embedder=embedder,
        repo_manager=repo_manager,
        indexer=indexer,
        syncer=syncer,
        context_store=context_store,
        search_engine=search_engine,
    )
```

**CLI usage:**
```python
# cli/app.py
_ctx: AppContext | None = None

async def get_context() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = await create_app()
    return _ctx
```

**MCP server usage:** `create_app()` is called once at server startup. The `AppContext` is stored as module state and accessed by each tool handler.

**Lazy LLM/embedding:** The `llm` and `embedder` objects are always constructed, but they defer heavy initialization (API client setup, model download) to the first actual call. Commands that don't need LLM/embeddings (like `list`, `status`, `config`) pay no startup cost.

---

## 11. Dependencies

### 11.1 `pyproject.toml` Dependencies

```toml
[project]
dependencies = [
    # CLI
    "typer>=0.9",
    "rich>=13.0",

    # MCP server
    "mcp>=1.0",

    # LLM
    "anthropic>=0.40",

    # Embeddings
    "sentence-transformers>=3.0",

    # Vector storage
    "sqlite-vec>=0.1",

    # Async SQLite
    "aiosqlite>=0.20",

    # Ignore file parsing
    "pathspec>=0.12",

    # Token counting
    "tiktoken>=0.7",

    # AST parsing
    "tree-sitter>=0.23",
]

[project.optional-dependencies]
# Tree-sitter grammars — install per-language as needed
tree-sitter-python = ["tree-sitter-python>=0.23"]
tree-sitter-javascript = ["tree-sitter-javascript>=0.23"]
tree-sitter-typescript = ["tree-sitter-typescript>=0.23"]
tree-sitter-go = ["tree-sitter-go>=0.23"]
tree-sitter-rust = ["tree-sitter-rust>=0.23"]
tree-sitter-java = ["tree-sitter-java>=0.23"]
tree-sitter-ruby = ["tree-sitter-ruby>=0.23"]
tree-sitter-cpp = ["tree-sitter-cpp>=0.23"]

# All supported grammars
all-grammars = [
    "codetex-mcp[tree-sitter-python]",
    "codetex-mcp[tree-sitter-javascript]",
    "codetex-mcp[tree-sitter-typescript]",
    "codetex-mcp[tree-sitter-go]",
    "codetex-mcp[tree-sitter-rust]",
    "codetex-mcp[tree-sitter-java]",
    "codetex-mcp[tree-sitter-ruby]",
    "codetex-mcp[tree-sitter-cpp]",
]

dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

### 11.2 Dependency Rationale

| Dependency | Why |
|---|---|
| `typer` + `rich` | Type-hint-driven CLI with rich terminal output, progress bars, markdown rendering |
| `mcp` | Official MCP Python SDK — provides FastMCP server framework |
| `anthropic` | Official Anthropic SDK for Claude API calls |
| `sentence-transformers` | Local embedding model (no external API dependency) |
| `sqlite-vec` | Vector similarity search as a SQLite extension (no separate vector DB) |
| `aiosqlite` | Async SQLite access for non-blocking I/O in the MCP server |
| `pathspec` | Parse `.gitignore`-style pattern files (battle-tested library) |
| `tiktoken` | Exact BPE token counting for cost estimation |
| `tree-sitter` | Language-agnostic AST parsing |

---

## 12. Design Decisions

### 12.1 Single SQLite Database for All Repos

**Decision:** One `~/.codetex/codetex.db` file, with all tables scoped by `repo_id` foreign key.

**Rationale:** Simpler backup/restore, single connection pool, enables cross-repo queries in the future. Multi-repo is architecture-ready from day one even though MVP focuses on single-repo workflows.

**Trade-off:** A corrupted database affects all repos. Mitigation: WAL mode + per-batch commits minimize corruption risk. If corruption occurs, the user can delete and re-index.

### 12.2 No Dependency Injection Framework

**Decision:** A single `create_app()` factory function wires the object graph manually.

**Rationale:** The object graph is small (~10 components) and static. A DI framework adds complexity without proportional benefit. Manual wiring is explicit and easy to test (pass mock dependencies directly to constructors).

### 12.3 Tree-sitter Grammars as Optional Extras

**Decision:** `tree-sitter` is a core dependency but individual language grammars are optional pip extras.

**Rationale:** Each grammar adds ~5-15MB. Installing all grammars for a user who only indexes Python is wasteful. The system auto-detects needed languages and falls back gracefully if a grammar isn't installed. Users can install grammars for their specific languages: `pip install codetex-mcp[tree-sitter-python,tree-sitter-typescript]`.

### 12.4 Lazy Embedding Model Loading

**Decision:** The `sentence-transformers` model is downloaded and loaded on the first call, not at startup.

**Rationale:** First-run model download is ~23MB and takes a few seconds. Commands that don't need embeddings (`add`, `list`, `config`, `status`) should be instant. The download only happens once, ever.

### 12.5 Interrupt-Resumable Indexing

**Decision:** Per-file/batch commits during indexing pipeline, with skip logic for already-indexed files.

**Rationale:** Indexing a large repo can take minutes. If the user interrupts (Ctrl+C), all progress up to the last committed batch is preserved. Re-running `index` picks up where it left off by checking which files already have records for the current session.

**Implementation detail:** Each indexing session stamps files with a `session_id` (the target commit SHA). On resume, only files without a record matching the current commit are processed.

### 12.6 Subprocess Git (Not GitPython)

**Decision:** Call the `git` binary via `asyncio.create_subprocess_exec` instead of using `gitpython`.

**Rationale:** Eliminates a heavy dependency. The `git` binary is already installed on every developer machine. Subprocess calls are simpler, more predictable, and delegate all authentication to the user's existing git/SSH configuration without any credential handling in our code.

### 12.7 sqlite-vec for Vector Storage

**Decision:** Use `sqlite-vec` SQLite extension instead of a separate vector database (ChromaDB, etc.).

**Rationale:** Keeps all data in a single SQLite file. No additional process to manage. For the scale of a single repo's index (hundreds to low thousands of vectors), sqlite-vec provides adequate performance for nearest-neighbor queries. Simplifies deployment and backup.

---

## 13. Future Extensibility

These are **not** built for MVP but the architecture explicitly leaves room for them:

### 13.1 Multi-Repo Cross-References

The `dependencies` table stores `target_path` as a string that may reference external packages. A future version could resolve these to other registered repos and build cross-repo dependency graphs.

### 13.2 Additional LLM Providers

The `LLMProvider` ABC makes adding new providers (OpenAI, local models via Ollama, etc.) a matter of implementing the abstract methods and adding a factory branch:

```python
# Future addition
if settings.llm_provider == "openai":
    llm = OpenAIProvider(api_key=..., model=...)
elif settings.llm_provider == "ollama":
    llm = OllamaProvider(base_url=..., model=...)
```

### 13.3 API-Based Embeddings

The `Embedder` class can be extended to support API-based embeddings (OpenAI, Cohere) by making `embed()` async and adding a provider abstraction similar to `LLMProvider`.

### 13.4 Real-Time File Watching

The sync pipeline's design (diff-based, scoped updates) is compatible with a future file-watcher mode that triggers mini-syncs on file save events.

### 13.5 Additional Languages for Tree-sitter

Adding a new language requires only installing the grammar package (`tree-sitter-{lang}`) and adding the file-extension-to-language mapping in the parser dispatcher. No core changes needed.

---

## 14. FR Traceability Matrix

Every functional requirement from the PRD is mapped to its implementing component(s).

| FR | Description | Components |
|---|---|---|
| FR-1 | Clone repos to managed directory | `RepoManager.add_remote`, `GitOperations.clone`, `Settings.repos_dir` |
| FR-2 | Register local repos without cloning | `RepoManager.add_local` |
| FR-3 | 3-tier context index | `Indexer` (pipeline Steps 4-9), `repo_overviews`, `files`, `symbols` tables |
| FR-4 | Tier 1 content | `prompts.tier1_prompt`, `repo_overviews` table |
| FR-5 | Tier 2 content | `prompts.tier2_prompt`, `files.summary`, `files.role` |
| FR-6 | Tier 3 content | `prompts.tier3_prompt`, `symbols.summary`, `symbols.calls_json` |
| FR-7 | Static analysis without LLM | `TreeSitterParser`, `FallbackParser`, `Parser` |
| FR-8 | LLM summarization | `LLMProvider.summarize_batch`, `prompts.py` |
| FR-9 | Record indexed commit SHA | `repositories.indexed_commit` |
| FR-10 | Detect current HEAD | `GitOperations.get_head_commit` |
| FR-11 | Incremental diff-based update | `Syncer.sync`, `GitOperations.diff_commits` |
| FR-12 | MCP server (stdio) | `server/mcp_server.py`, FastMCP |
| FR-13 | CLI commands | `cli/app.py` — `add`, `index`, `sync`, `context`, `status`, `list`, `serve`, `config` |
| FR-14 | SQLite storage | `storage/database.py`, all tables |
| FR-15 | Configurable exclusion patterns | `Settings.default_excludes`, `IgnoreFilter` |
| FR-16 | Language-agnostic | `Parser` dispatch (tree-sitter with fallback) |
| FR-17 | Configurable LLM provider | `LLMProvider` ABC, `Settings.llm_provider/llm_model` |
| FR-18 | `--dry-run` flag | `Indexer.index(dry_run=True)`, `Syncer.sync(dry_run=True)` |
| FR-19 | `.gitignore` + `.codetexignore` | `IgnoreFilter` with pathspec |
| FR-20 | Conditional Tier 1 rebuild | `Syncer` Step 6, `Settings.tier1_rebuild_threshold` |
| FR-21 | Tree-sitter with fallback | `TreeSitterParser`, `FallbackParser`, optional grammar extras |
| FR-22 | Vector embeddings for semantic search | `Embedder`, `vec_file_embeddings`, `vec_symbol_embeddings`, `SearchEngine` |
| FR-23 | Partial indexing via `--path` | `Indexer.index(path_filter=...)`, `Syncer.sync(path_filter=...)` |
| FR-24 | Git auth delegation | `GitOperations` (subprocess git), `GitAuthError` |
| FR-25 | `--path` on index and sync | Same as FR-23 |
| FR-26 | Local embedding model | `Embedder` (sentence-transformers, all-MiniLM-L6-v2) |
| FR-27 | Exact token counts via tiktoken | `FileAnalysis.token_count`, `files.token_count` column |
| FR-28 | Concurrent LLM calls with backoff | `RateLimiter`, `Settings.max_concurrent_llm_calls` |
