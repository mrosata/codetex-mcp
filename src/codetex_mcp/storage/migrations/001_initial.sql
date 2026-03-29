-- Initial schema for codetex-mcp
-- Creates all 6 main tables and 2 sqlite-vec virtual tables

CREATE TABLE IF NOT EXISTS repositories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    remote_url      TEXT,
    local_path      TEXT NOT NULL,
    default_branch  TEXT NOT NULL DEFAULT 'main',
    indexed_commit  TEXT,
    last_indexed_at TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    language        TEXT,
    lines_of_code   INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER NOT NULL DEFAULT 0,
    role            TEXT,
    summary         TEXT,
    imports_json    TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_id, path)
);

CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo_id);
CREATE INDEX IF NOT EXISTS idx_files_repo_path ON files(repo_id, path);

CREATE TABLE IF NOT EXISTS symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    signature       TEXT NOT NULL,
    docstring       TEXT,
    summary         TEXT,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    parameters_json TEXT,
    return_type     TEXT,
    calls_json      TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_repo ON symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(repo_id, name);

CREATE TABLE IF NOT EXISTS dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    source_file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target_path     TEXT NOT NULL,
    imported_names  TEXT,
    UNIQUE(source_file_id, target_path)
);

CREATE INDEX IF NOT EXISTS idx_deps_repo ON dependencies(repo_id);
CREATE INDEX IF NOT EXISTS idx_deps_source ON dependencies(source_file_id);

CREATE TABLE IF NOT EXISTS repo_overviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    overview        TEXT NOT NULL,
    directory_tree  TEXT,
    technologies    TEXT,
    commit_sha      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_file_embeddings USING vec0(
    file_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_symbol_embeddings USING vec0(
    symbol_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
