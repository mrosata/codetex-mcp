from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from codetex_mcp.exceptions import ConfigError

_DEFAULT_EXCLUDES = [
    "node_modules/",
    "vendor/",
    "__pycache__/",
    ".git/",
    "*.min.js",
    "*.min.css",
    "*.lock",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "dist/",
    "build/",
    ".tox/",
    ".venv/",
    "venv/",
]


@dataclass
class Settings:
    # Storage
    data_dir: Path = field(default_factory=lambda: Path.home() / ".codetex")
    repos_dir: Path | None = None  # Derived from data_dir if not set
    db_path: Path | None = None  # Derived from data_dir if not set

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5-20250929"
    llm_api_key: str | None = None

    # Indexing
    max_file_size_kb: int = 512
    max_concurrent_llm_calls: int = 5
    tier1_rebuild_threshold: float = 0.10
    default_excludes: list[str] = field(default_factory=lambda: list(_DEFAULT_EXCLUDES))

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"

    def __post_init__(self) -> None:
        if self.repos_dir is None:
            self.repos_dir = self.data_dir / "repos"
        if self.db_path is None:
            self.db_path = self.data_dir / "codetex.db"

    @classmethod
    def load(cls) -> Settings:
        """Load settings: hardcoded defaults → TOML file → env vars (last wins)."""
        settings = cls()

        # Check env var for data_dir early so we find the TOML in the right place
        if env_data_dir := os.environ.get("CODETEX_DATA_DIR"):
            settings.data_dir = Path(env_data_dir).expanduser()

        # Layer 2: TOML config file
        config_path = settings.data_dir / "config.toml"
        if config_path.exists():
            settings = cls._apply_toml(settings, config_path)

        # Layer 3: Environment variables
        settings = cls._apply_env(settings)

        # Derive paths after all overrides
        settings.repos_dir = settings.data_dir / "repos"
        settings.db_path = settings.data_dir / "codetex.db"

        # Create directories
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.repos_dir.mkdir(parents=True, exist_ok=True)

        return settings

    @classmethod
    def _apply_toml(cls, settings: Settings, config_path: Path) -> Settings:
        """Apply TOML config file overrides."""
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in {config_path}: {e}") from e

        storage = data.get("storage", {})
        if "data_dir" in storage:
            settings.data_dir = Path(storage["data_dir"]).expanduser()

        llm = data.get("llm", {})
        if "provider" in llm:
            settings.llm_provider = llm["provider"]
        if "model" in llm:
            settings.llm_model = llm["model"]
        if "api_key" in llm:
            settings.llm_api_key = llm["api_key"]

        indexing = data.get("indexing", {})
        if "max_file_size_kb" in indexing:
            settings.max_file_size_kb = int(indexing["max_file_size_kb"])
        if "max_concurrent_llm_calls" in indexing:
            settings.max_concurrent_llm_calls = int(
                indexing["max_concurrent_llm_calls"]
            )
        if "tier1_rebuild_threshold" in indexing:
            settings.tier1_rebuild_threshold = float(
                indexing["tier1_rebuild_threshold"]
            )
        if "exclude_patterns" in indexing:
            settings.default_excludes = indexing["exclude_patterns"]

        embedding = data.get("embedding", {})
        if "model" in embedding:
            settings.embedding_model = embedding["model"]

        return settings

    @classmethod
    def _apply_env(cls, settings: Settings) -> Settings:
        """Apply environment variable overrides."""
        if val := os.environ.get("CODETEX_DATA_DIR"):
            settings.data_dir = Path(val).expanduser()

        if val := os.environ.get("CODETEX_LLM_PROVIDER"):
            settings.llm_provider = val

        if val := os.environ.get("CODETEX_LLM_MODEL"):
            settings.llm_model = val

        if val := os.environ.get("ANTHROPIC_API_KEY"):
            settings.llm_api_key = val

        if val := os.environ.get("CODETEX_MAX_FILE_SIZE_KB"):
            settings.max_file_size_kb = int(val)

        if val := os.environ.get("CODETEX_MAX_CONCURRENT_LLM"):
            settings.max_concurrent_llm_calls = int(val)

        if val := os.environ.get("CODETEX_TIER1_THRESHOLD"):
            settings.tier1_rebuild_threshold = float(val)

        if val := os.environ.get("CODETEX_EMBEDDING_MODEL"):
            settings.embedding_model = val

        return settings
