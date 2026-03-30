from __future__ import annotations

from pathlib import Path

import pytest

from codetex_mcp.config.settings import Settings
from codetex_mcp.exceptions import ConfigError


class TestSettingsDefaults:
    def test_default_data_dir(self) -> None:
        s = Settings()
        assert s.data_dir == Path.home() / ".codetex"

    def test_default_repos_dir(self) -> None:
        s = Settings()
        assert s.repos_dir == Path.home() / ".codetex" / "repos"

    def test_default_db_path(self) -> None:
        s = Settings()
        assert s.db_path == Path.home() / ".codetex" / "codetex.db"

    def test_default_llm_provider(self) -> None:
        s = Settings()
        assert s.llm_provider == "anthropic"

    def test_default_llm_model(self) -> None:
        s = Settings()
        assert s.llm_model == "claude-sonnet-4-5-20250929"

    def test_default_llm_api_key_is_none(self) -> None:
        s = Settings()
        assert s.llm_api_key is None

    def test_default_max_file_size_kb(self) -> None:
        s = Settings()
        assert s.max_file_size_kb == 512

    def test_default_max_concurrent_llm_calls(self) -> None:
        s = Settings()
        assert s.max_concurrent_llm_calls == 5

    def test_default_tier1_rebuild_threshold(self) -> None:
        s = Settings()
        assert s.tier1_rebuild_threshold == 0.10

    def test_default_excludes_not_empty(self) -> None:
        s = Settings()
        assert len(s.default_excludes) > 0
        assert "node_modules/" in s.default_excludes
        assert "__pycache__/" in s.default_excludes
        assert ".git/" in s.default_excludes
        assert "*.min.js" in s.default_excludes
        assert "*.lock" in s.default_excludes

    def test_default_embedding_model(self) -> None:
        s = Settings()
        assert s.embedding_model == "all-MiniLM-L6-v2"

    def test_default_excludes_are_independent_copies(self) -> None:
        s1 = Settings()
        s2 = Settings()
        s1.default_excludes.append("extra/")
        assert "extra/" not in s2.default_excludes


class TestSettingsTomlOverride:
    def test_toml_overrides_all_fields(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".codetex"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """\
[storage]
data_dir = "/custom/data"

[llm]
provider = "openai"
model = "gpt-4"
api_key = "sk-test-key"

[indexing]
max_file_size_kb = 1024
max_concurrent_llm_calls = 10
tier1_rebuild_threshold = 0.25
exclude_patterns = ["custom_exclude/"]

[embedding]
model = "custom-model"
"""
        )

        s = Settings(data_dir=config_dir)
        s = Settings._apply_toml(s, config_file)

        assert s.data_dir == Path("/custom/data")
        assert s.llm_provider == "openai"
        assert s.llm_model == "gpt-4"
        assert s.llm_api_key == "sk-test-key"
        assert s.max_file_size_kb == 1024
        assert s.max_concurrent_llm_calls == 10
        assert s.tier1_rebuild_threshold == 0.25
        assert s.default_excludes == ["custom_exclude/"]
        assert s.embedding_model == "custom-model"

    def test_toml_partial_override(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """\
[llm]
model = "claude-opus-4-20250916"
"""
        )

        s = Settings()
        s = Settings._apply_toml(s, config_file)

        assert s.llm_model == "claude-opus-4-20250916"
        # Other defaults preserved
        assert s.llm_provider == "anthropic"
        assert s.max_file_size_kb == 512

    def test_toml_invalid_raises_config_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text("invalid [[ toml content")

        s = Settings()
        with pytest.raises(ConfigError, match="Invalid TOML"):
            Settings._apply_toml(s, config_file)

    def test_toml_data_dir_tilde_expansion(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """\
[storage]
data_dir = "~/my-codetex"
"""
        )

        s = Settings()
        s = Settings._apply_toml(s, config_file)
        assert s.data_dir == Path.home() / "my-codetex"


class TestSettingsEnvOverride:
    def test_env_overrides_data_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODETEX_DATA_DIR", "/env/data")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.data_dir == Path("/env/data")

    def test_env_overrides_llm_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODETEX_LLM_PROVIDER", "openai")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.llm_provider == "openai"

    def test_env_overrides_llm_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODETEX_LLM_MODEL", "gpt-4")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.llm_model == "gpt-4"

    def test_env_overrides_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.llm_api_key == "sk-env-key"

    def test_env_overrides_max_file_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODETEX_MAX_FILE_SIZE_KB", "2048")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.max_file_size_kb == 2048

    def test_env_overrides_max_concurrent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODETEX_MAX_CONCURRENT_LLM", "20")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.max_concurrent_llm_calls == 20

    def test_env_overrides_tier1_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODETEX_TIER1_THRESHOLD", "0.50")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.tier1_rebuild_threshold == 0.50

    def test_env_overrides_embedding_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODETEX_EMBEDDING_MODEL", "custom-embed")
        s = Settings()
        s = Settings._apply_env(s)
        assert s.embedding_model == "custom-embed"


class TestSettingsLoad:
    def test_load_creates_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data_dir = tmp_path / "codetex-data"
        monkeypatch.setenv("CODETEX_DATA_DIR", str(data_dir))
        # Clear any ANTHROPIC_API_KEY that might be set
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        s = Settings.load()

        assert s.data_dir == data_dir
        assert data_dir.exists()
        assert (data_dir / "repos").exists()
        assert s.repos_dir == data_dir / "repos"
        assert s.db_path == data_dir / "codetex.db"

    def test_load_toml_then_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env vars override TOML values (last wins)."""
        data_dir = tmp_path / "codetex-data"
        data_dir.mkdir()
        config_file = data_dir / "config.toml"
        config_file.write_text(
            """\
[llm]
model = "from-toml"
api_key = "from-toml-key"
"""
        )

        monkeypatch.setenv("CODETEX_DATA_DIR", str(data_dir))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env-key")

        s = Settings.load()

        # TOML set the model
        assert s.llm_model == "from-toml"
        # Env var overrode the api_key
        assert s.llm_api_key == "from-env-key"

    def test_load_without_toml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Load works when no config.toml exists."""
        data_dir = tmp_path / "no-config"
        monkeypatch.setenv("CODETEX_DATA_DIR", str(data_dir))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        s = Settings.load()

        assert s.llm_provider == "anthropic"
        assert s.llm_model == "claude-sonnet-4-5-20250929"
