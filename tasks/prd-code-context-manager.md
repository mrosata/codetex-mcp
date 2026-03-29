# PRD: Code Context Manager (codetex-mcp)

## Introduction

Code Context Manager is an open-source MCP server and CLI tool that maintains intelligent, commit-aware context about code repositories. It solves a fundamental problem when using LLMs for software engineering: LLMs lack persistent, structured understanding of large codebases and lose context between sessions.

The tool clones repositories locally, builds a multi-layered index of knowledge (from high-level architecture down to function-level details), and tracks what it knows per commit. When a developer moves to a different commit, the tool calculates the diff and incrementally updates its understanding rather than re-indexing from scratch. This context is exposed to LLMs via the Model Context Protocol (MCP), giving them on-demand access to structured codebase knowledge.

The MVP targets a single repository. The architecture must support multiple independent repositories, with a future vision of cross-service relationship mapping.

## Goals

- Provide LLMs with structured, multi-granularity context about a codebase without requiring the LLM to read every file
- Maintain context that stays current with the developer's working commit via incremental diff-based updates
- Reduce token usage and improve LLM response quality by serving pre-indexed, relevant context instead of raw file dumps
- Operate entirely locally with no external service dependencies beyond optional LLM API calls for summarization
- Expose context through both MCP (for LLM tool use) and CLI (for developer inspection and debugging)
- Ship as a usable open-source tool with clear documentation and reasonable developer UX

## User Stories

### US-001: Clone and register a repository
**Description:** As a developer, I want to register a git repository with codetex so it can begin building context about my codebase.

**Acceptance Criteria:**
- [ ] CLI command `codetex add <repo-url>` clones the repo to a managed local directory (e.g., `~/.codetex/repos/<repo-name>/`)
- [ ] CLI command `codetex add <local-path>` registers an already-cloned local repo without duplicating it
- [ ] The tool records the repo's remote URL, local path, current HEAD commit, and default branch in its database
- [ ] If the repo is already registered, the command returns an informative message instead of duplicating
- [ ] `codetex list` shows all registered repositories with their current indexed commit
- [ ] Typecheck/lint passes

### US-002: Build initial context index for a repository
**Description:** As a developer, I want codetex to analyze my repository and build a structured knowledge index so that LLMs can understand my codebase.

**Acceptance Criteria:**
- [ ] CLI command `codetex index <repo-name>` triggers a full index build
- [ ] CLI command `codetex index <repo-name> --path <dir-or-glob>` indexes only matching files/directories (partial indexing)
- [ ] CLI command `codetex index <repo-name> --dry-run` shows what files would be indexed, estimated LLM calls, and approximate token cost — without making any API calls
- [ ] **Tier 1 (Repo Overview):** Generates a high-level summary including: purpose/description, directory structure, key technologies/frameworks detected, entry points, and overall architecture patterns
- [ ] **Tier 2 (File/Module Summaries):** For each source file, generates: a one-paragraph summary of purpose, list of exports/public interfaces, dependencies (imports), and file role classification (e.g., model, controller, utility, config, test)
- [ ] **Tier 3 (Symbol Details):** For key functions/classes, generates: signature, docstring/summary, parameters and return types, internal dependencies and call relationships
- [ ] Static analysis extracts structure (file tree, imports, exports, function signatures) without LLM calls
- [ ] LLM-generated summaries are produced for Tier 1 overview and Tier 2/3 items that benefit from natural language explanation
- [ ] The indexed commit SHA is recorded in the database
- [ ] Progress is displayed during indexing (file count, percentage, current file)
- [ ] Indexing can be interrupted and resumed
- [ ] Typecheck/lint passes

### US-003: Detect current commit and update context incrementally
**Description:** As a developer, I want codetex to detect when my working commit has changed and update only the affected parts of its index, so context stays current without expensive full re-indexing.

**Acceptance Criteria:**
- [ ] CLI command `codetex sync <repo-name>` checks the repo's current HEAD against the last indexed commit
- [ ] If commits differ, the tool computes `git diff` between the indexed commit and current HEAD
- [ ] Only files that changed in the diff are re-analyzed and their index entries updated
- [ ] For modified files: Tier 2 and Tier 3 entries are regenerated
- [ ] For added files: new Tier 2 and Tier 3 entries are created
- [ ] For deleted files: corresponding index entries are removed
- [ ] If the diff affects >= 10% of indexed files, Tier 1 is regenerated (threshold configurable via `tier1_rebuild_threshold`)
- [ ] `codetex sync <repo-name> --dry-run` shows what would be updated and estimated token cost without making API calls
- [ ] The indexed commit SHA is updated to the current HEAD after successful sync
- [ ] If the repo is already at the indexed commit, the command reports "already up to date"
- [ ] Typecheck/lint passes

### US-004: Query context via CLI
**Description:** As a developer, I want to query the indexed context from the command line so I can inspect what the tool knows and debug its understanding.

**Acceptance Criteria:**
- [ ] `codetex context <repo-name>` returns the Tier 1 repo overview
- [ ] `codetex context <repo-name> --file <path>` returns the Tier 2 summary for a specific file
- [ ] `codetex context <repo-name> --symbol <name>` returns the Tier 3 detail for a function/class
- [ ] `codetex context <repo-name> --query "<question>"` performs semantic search over indexed context using embeddings and returns relevant results
- [ ] Output is formatted as readable markdown in the terminal
- [ ] `codetex status <repo-name>` shows: indexed commit, current HEAD commit, number of indexed files, last sync time, whether sync is needed
- [ ] Typecheck/lint passes

### US-005: Serve context via MCP server
**Description:** As a developer using Claude (or another MCP-compatible LLM), I want codetex to expose its indexed context as MCP tools so the LLM can query codebase knowledge on demand.

**Acceptance Criteria:**
- [ ] `codetex serve` starts an MCP server (stdio transport)
- [ ] MCP tool `get_repo_overview` returns the Tier 1 summary for a registered repo
- [ ] MCP tool `get_file_context` accepts a file path and returns its Tier 2 summary
- [ ] MCP tool `get_symbol_detail` accepts a symbol name and returns its Tier 3 detail
- [ ] MCP tool `search_context` accepts a natural language query and returns relevant indexed context
- [ ] MCP tool `get_repo_status` returns current index status (indexed commit, staleness, file count)
- [ ] MCP tool `sync_repo` triggers an incremental sync and returns a summary of what changed
- [ ] All tools return structured, well-formatted responses suitable for LLM consumption
- [ ] Server can be configured in Claude Code's MCP settings (`claude_desktop_config.json` or `.mcp.json`)
- [ ] Typecheck/lint passes

### US-006: Configure tool behavior
**Description:** As a developer, I want to configure codetex's behavior (storage location, LLM provider, indexing preferences) so it fits my workflow.

**Acceptance Criteria:**
- [ ] Configuration stored in `~/.codetex/config.toml` (or similar)
- [ ] Configurable: storage directory for cloned repos and index data
- [ ] Configurable: LLM provider and model for summarization (default: Anthropic Claude)
- [ ] Configurable: API key for LLM provider (via config file or environment variable)
- [ ] Configurable: file patterns to exclude from indexing (e.g., `node_modules/`, `*.min.js`, vendor dirs)
- [ ] Configurable: maximum file size threshold for indexing
- [ ] `codetex config show` displays current configuration
- [ ] `codetex config set <key> <value>` updates a config value
- [ ] Sensible defaults work out of the box (only API key is required)
- [ ] Typecheck/lint passes

### US-008: Configure indexing scope with .codetexignore
**Description:** As a developer, I want to control which files and directories are indexed using a familiar ignore-file pattern, so I can exclude irrelevant code and reduce indexing cost.

**Acceptance Criteria:**
- [ ] The tool respects `.codetexignore` files placed in the repo root, using the same syntax as `.gitignore`
- [ ] The tool also respects the repo's `.gitignore` — files ignored by git are ignored by codetex by default
- [ ] `.codetexignore` can override `.gitignore` — a file ignored by git can be explicitly included via `!pattern` in `.codetexignore`
- [ ] Conversely, `.codetexignore` can exclude files that are tracked by git
- [ ] Default excludes are applied even without a `.codetexignore` file (e.g., `node_modules/`, `vendor/`, `__pycache__/`, `*.min.js`, `*.lock`, `*.map`)
- [ ] `codetex index <repo-name> --dry-run` shows which files are excluded and why (gitignore, codetexignore, size threshold, binary)
- [ ] Typecheck/lint passes

### US-009: Authenticate and clone private repositories
**Description:** As a developer, I want codetex to handle private repositories so I can index codebases that require authentication.

**Acceptance Criteria:**
- [ ] `codetex add <repo-url>` works with private repos accessible via SSH keys (`git@github.com:...`)
- [ ] `codetex add <repo-url>` works with private repos accessible via HTTPS + credential helpers configured in git
- [ ] The tool delegates authentication to the user's existing git configuration — it does not store credentials itself
- [ ] If a clone fails due to authentication, the error message clearly explains what went wrong and suggests SSH or credential helper setup
- [ ] Typecheck/lint passes

### US-007: Handle large repositories efficiently
**Description:** As a developer working on large codebases, I want codetex to handle repos with thousands of files without excessive resource usage or indexing time.

**Acceptance Criteria:**
- [ ] Files matching ignore patterns (`.gitignore`, configured excludes) are skipped
- [ ] Binary files and files above the size threshold are skipped with a logged notice
- [ ] Indexing uses batched LLM calls to minimize API round-trips
- [ ] Index data is stored efficiently (no redundant re-processing of unchanged files on re-index)
- [ ] Memory usage stays reasonable during indexing (streaming/batched processing, not loading all files at once)
- [ ] Typecheck/lint passes

## Functional Requirements

- FR-1: The system must clone git repositories to a managed local directory (`~/.codetex/repos/` by default)
- FR-2: The system must register local repository paths without cloning if the repo already exists locally
- FR-3: The system must build a 3-tier context index: Repo Overview (Tier 1), File/Module Summaries (Tier 2), Symbol Details (Tier 3)
- FR-4: Tier 1 must include: repo purpose, directory structure map, detected technologies, entry points, and architecture summary
- FR-5: Tier 2 must include per-file: purpose summary, public interface list, dependency list, and role classification
- FR-6: Tier 3 must include per-symbol: signature, description, parameters/return types, and internal call relationships
- FR-7: Static analysis must extract file trees, import/export graphs, and function/class signatures without LLM calls
- FR-8: LLM summarization must be used for natural language descriptions at all three tiers
- FR-9: The system must record the git commit SHA for which the index was built
- FR-10: The system must detect the current HEAD commit of a registered repository
- FR-11: When the current commit differs from the indexed commit, the system must compute a git diff and update only affected index entries
- FR-12: The system must expose indexed context through an MCP server using stdio transport
- FR-13: The system must provide CLI commands for all core operations: `add`, `index`, `sync`, `context`, `status`, `list`, `serve`, `config`
- FR-14: The system must persist index data in a SQLite database
- FR-15: The system must support configurable file exclusion patterns and size thresholds
- FR-16: The system must be language-agnostic, treating source files as text with structural extraction where feasible
- FR-17: The system must support configurable LLM providers for the summarization step
- FR-18: The system must provide a `--dry-run` flag on `index` and `sync` commands that displays estimated LLM calls and token cost without making API requests
- FR-19: The system must respect `.gitignore` patterns by default and support a `.codetexignore` file for additional include/exclude control
- FR-20: Tier 1 rebuild on sync must be triggered when >= 10% of indexed files are affected (configurable via `tier1_rebuild_threshold`)
- FR-21: The system must use tree-sitter for AST parsing with on-demand grammar loading (only grammars for detected languages), falling back to line-based extraction for unsupported languages
- FR-22: The system must generate and store vector embeddings for all indexed context to enable semantic search via `search_context` and `--query`
- FR-23: The system must support partial indexing via `--path` flag to restrict indexing to specific directories or glob patterns
- FR-24: The system must delegate git authentication to the user's existing git/SSH configuration and provide clear error messages on auth failure
- FR-25: The `index` and `sync` commands must support `--path` for partial indexing of specific directories or file patterns
- FR-26: The system must use a local embedding model (auto-downloaded on first run) for vector embeddings — no external API dependency for embeddings
- FR-27: The system must store exact token counts per file using `tiktoken` and update them incrementally on diff-based syncs
- FR-28: The indexing pipeline must support configurable concurrent LLM calls (default: 5) with exponential backoff on rate limits

## Non-Goals (Out of Scope for MVP)

- **Multi-repo relationship mapping:** Understanding cross-service dependencies (e.g., API caller/callee relationships between repos) is a future goal, not MVP
- **Real-time file watching:** The tool syncs on explicit command or MCP tool call, not via filesystem watchers
- **Code generation or modification:** The tool provides context only; it does not write or modify code
- **Remote/cloud storage:** All data is stored locally; no cloud sync or shared storage
- **IDE plugins:** No VS Code, JetBrains, or other IDE integrations for MVP (MCP covers LLM integration)
- **Automatic commit detection:** The tool does not run as a background daemon auto-detecting commits; sync is user-triggered
- **Support for non-git VCS:** Only git repositories are supported
- **Fine-grained access control:** No permissions model; the tool trusts local access
- **Caching or serving raw file contents:** The tool serves indexed knowledge, not raw source code

## Technical Considerations

- **Language:** Python 3.12+, managed with `uv`
- **MCP SDK:** Use the official `mcp` Python SDK for MCP server implementation
- **Git interaction:** Use `gitpython` or subprocess calls to `git` for clone, diff, log, and status operations
- **Static analysis:** Use `tree-sitter` for language-agnostic AST parsing with on-demand grammar loading (only download/load grammars for languages detected in the repo). Fall back to line-based extraction for languages without a tree-sitter grammar
- **LLM integration:** Use `anthropic` SDK by default; abstract behind a provider interface for future extensibility (OpenAI, local models, etc.)
- **Storage:** SQLite via `sqlite3` stdlib or `aiosqlite` for async access. Schema must support multiple repos from the start even though MVP focuses on one
- **Embeddings:** Local-only for MVP using `sentence-transformers` (auto-downloads a small model ~30-90MB on first run, CPU-only, no user setup required). Store vectors in SQLite via `sqlite-vec` extension or ChromaDB. Must support semantic similarity search for `--query` and MCP `search_context`
- **Token counting:** Use `tiktoken` for exact per-file token counts, stored in the database. On diff-based sync, only re-tokenize changed files (added/modified) and subtract deleted files — making dry-run estimates near-instant after initial index
- **Concurrency:** Indexing pipeline supports concurrent LLM calls with a configurable concurrency limit (default: 5). Includes exponential backoff for rate limit handling. Configurable via `max_concurrent_llm_calls` in config
- **CLI framework:** Use `click` or `typer` for CLI command structure
- **Configuration:** TOML-based config file using `tomllib` (stdlib in 3.11+)
- **Packaging:** Distribute as a Python package installable via `uv tool install` or `pipx`
- **Testing:** `pytest` for unit and integration tests
- **Architecture:** The data model and storage layer must be designed for multi-repo from day one, even if the MVP UX only exercises single-repo workflows

## Success Metrics

- A developer can register a medium-complexity repo (~500 files) and have it fully indexed within 10 minutes
- Incremental sync on a 10-file diff completes in under 30 seconds
- An LLM using the MCP tools can answer architectural questions about the codebase without reading raw files
- The tool can be installed and configured in under 5 minutes by following documentation
- Index storage for a 500-file repo stays under 50 MB
- The project has clear README, usage docs, and contribution guidelines suitable for open-source

## Resolved Decisions

1. **LLM cost management:** Yes — `--dry-run` flag on `index` and `sync` shows estimated LLM calls, token count, and approximate cost before making any API requests.
2. **Diff threshold for Tier 1 regeneration:** Default 10% of indexed files. Configurable via `tier1_rebuild_threshold` in config. Trade-off: lower threshold = more frequent (costly) rebuilds but fresher overviews; higher = cheaper but potentially stale overviews.
3. **Tree-sitter vs. simpler parsing:** Tree-sitter, with on-demand grammar loading. Only grammars for languages detected in the repo are downloaded. Fallback to line-based extraction for languages without a tree-sitter grammar.
4. **Embedding search:** Invest from the start. All indexed context gets vector embeddings for semantic search. Used by `--query` CLI flag and MCP `search_context` tool.
5. **Partial indexing:** Yes — `--path <dir-or-glob>` flag on `index` and `sync` restricts scope. Combined with `.codetexignore` for persistent exclusions.
6. **Auth for private repos:** Yes — delegate to the user's existing git/SSH config. No credential storage in codetex. Clear error messages on auth failure with setup guidance.

7. **Embedding model:** Local-only for MVP using `sentence-transformers`. Auto-downloads a small model on first run (~30-90MB). No user setup, no GPU, no external service. Runs on CPU. API-based embedding support deferred to post-MVP.
8. **Token cost estimation:** Exact counts via `tiktoken`, stored per file in the database. Incremental updates on diff (only re-tokenize changed files). Dry-run estimates are near-instant after initial index.
9. **Concurrent indexing:** Yes, with configurable concurrency (default: 5 parallel LLM calls). Exponential backoff on rate limits. Configurable via `max_concurrent_llm_calls`.

## Open Questions

- None remaining — all architectural decisions resolved. Ready for architecture document.
