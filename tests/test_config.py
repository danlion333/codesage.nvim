"""Tests for CodeSage configuration."""

import os
from pathlib import Path

import pytest

from codesage.config import CodeSageConfig, ModelsConfig, ServerConfig, load_config


class TestModelsConfig:
    def test_defaults(self):
        config = ModelsConfig()
        assert "claude" in config.default_model
        assert config.max_tokens == 4096
        assert config.temperature == 0.3


class TestServerConfig:
    def test_default_socket_path(self):
        config = ServerConfig()
        path = config.get_socket_path()
        assert path.startswith("/tmp/codesage-")
        assert path.endswith(".sock")

    def test_custom_socket_path(self):
        config = ServerConfig(socket_path="/custom/path.sock")
        assert config.get_socket_path() == "/custom/path.sock"


class TestCodeSageConfig:
    def test_defaults(self):
        config = CodeSageConfig()
        assert config.models.max_tokens == 4096
        assert config.ui.streaming is True
        assert config.privacy.telemetry is False

    def test_nested_override(self):
        config = CodeSageConfig(models={"default_model": "gpt-4o", "max_tokens": 2048})
        assert config.models.default_model == "gpt-4o"
        assert config.models.max_tokens == 2048

    def test_get_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        config = CodeSageConfig()
        assert config.get_api_key() == "sk-test-123"

    def test_get_api_key_by_provider(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-123")
        config = CodeSageConfig()
        assert config.get_api_key("openai") == "sk-openai-123"

    def test_get_api_key_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = CodeSageConfig()
        assert config.get_api_key() is None


class TestLoadConfig:
    def test_load_without_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert isinstance(config, CodeSageConfig)

    def test_load_with_project_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        toml_content = b'[models]\ndefault_model = "gpt-4o"\nmax_tokens = 2048\n'
        (tmp_path / ".codesage.toml").write_bytes(toml_content)
        config = load_config()
        assert config.models.default_model == "gpt-4o"
        assert config.models.max_tokens == 2048
