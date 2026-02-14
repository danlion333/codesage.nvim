"""Configuration management for CodeSage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Nested config models ---


class ModelsConfig(BaseModel):
    """LLM model configuration."""

    default_model: str = "anthropic/claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.3
    api_key_env: str = "ANTHROPIC_API_KEY"


class ContextConfig(BaseModel):
    """Context assembly configuration."""

    max_context_tokens: int = 8000
    include_imports: bool = True
    include_symbols: bool = True
    include_project_summary: bool = True
    include_related_symbols: bool = True
    max_file_tokens: int = 2000


class UIConfig(BaseModel):
    """UI configuration."""

    float_width: float = 0.7
    float_height: float = 0.6
    streaming: bool = True


class PrivacyConfig(BaseModel):
    """Privacy settings."""

    telemetry: bool = False
    send_filenames: bool = True
    send_file_contents: bool = True
    exclude_patterns: list[str] = [".env", "*.pem", "*.key", "credentials*", "secrets*"]


class AgenticConfig(BaseModel):
    """Agentic tool use configuration."""

    enabled: bool = True
    max_iterations: int = 20
    show_tool_calls: bool = True
    max_output_chars: int = 30_000
    allow_shell_commands: bool = False


class ServerConfig(BaseModel):
    """Server configuration."""

    socket_path: str = ""
    log_level: str = "INFO"

    def get_socket_path(self) -> str:
        """Return socket path, generating default if empty."""
        if self.socket_path:
            return self.socket_path
        return f"/tmp/codesage-{os.getpid()}.sock"


# --- Main config ---


class CodeSageConfig(BaseSettings):
    """Main CodeSage configuration.

    Loaded from (in order of precedence):
    1. Environment variables (CODESAGE_ prefix)
    2. Project-local .codesage.toml
    3. Global ~/.config/codesage/config.toml
    4. Defaults
    """

    model_config = SettingsConfigDict(
        env_prefix="CODESAGE_",
        env_nested_delimiter="__",
    )

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    agentic: AgenticConfig = Field(default_factory=AgenticConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    def get_api_key(self, provider: str | None = None) -> str | None:
        """Resolve API key from the configured environment variable.

        Args:
            provider: Optional provider name. If None, uses the env var
                     from models.api_key_env.

        Returns:
            The API key string, or None if not set.
        """
        if provider:
            env_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "google": "GEMINI_API_KEY",
                "minimax": "MINIMAX_API_KEY",
            }
            env_var = env_map.get(provider, f"{provider.upper()}_API_KEY")
        else:
            env_var = self.models.api_key_env
        return os.environ.get(env_var)


def load_config() -> CodeSageConfig:
    """Load configuration from TOML files and environment.

    Checks project-local .codesage.toml and global config.
    """
    config_data: dict[str, Any] = {}

    # Global config
    global_config = Path.home() / ".config" / "codesage" / "config.toml"
    if global_config.exists():
        config_data.update(_load_toml(global_config))

    # Project-local config (overrides global)
    local_config = Path(".codesage.toml")
    if local_config.exists():
        config_data.update(_load_toml(local_config))

    return CodeSageConfig(**config_data)


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    import tomllib

    with open(path, "rb") as f:
        return tomllib.load(f)
