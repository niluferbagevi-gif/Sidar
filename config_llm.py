"""LLM provider and semantic-cache configuration for Sidar."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaBatchPolicy:
    """Central Ollama num_batch bounds used by config and runtime clients."""

    def __init__(self, default: int = 2048, maximum: int = 4096, auto_min: int = 2048) -> None:
        self.default = default
        self.maximum = maximum
        self.auto_min = auto_min

    def clamp(self, value: int) -> int:
        """Clamp explicit num_batch values to the supported maximum."""
        return min(self.maximum, value)

    def auto_batch_for_context(self, num_ctx: int) -> int:
        """Resolve automatic num_batch for large Ollama context windows."""
        if num_ctx <= self.auto_min:
            return 0
        return min(self.maximum, num_ctx)


OLLAMA_BATCH_POLICY = OllamaBatchPolicy()
SUPPORTED_AI_PROVIDERS: frozenset[str] = frozenset(
    {"ollama", "gemini", "openai", "anthropic", "litellm"}
)
PROVIDER_REQUIRED_SETTINGS: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "litellm": ("LITELLM_GATEWAY_URL",),
}


class LLMClientSettings(BaseSettings):
    """LLM istemcisi için ortam değişkenlerini tip güvenli şekilde yükler."""

    model_config = SettingsConfigDict(env_file=None, env_file_encoding="utf-8", extra="ignore")

    AI_PROVIDER: str = "ollama"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BASE_DELAY: float = 0.4
    LLM_RETRY_MAX_DELAY: float = 4.0
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"
    ANTHROPIC_TIMEOUT: int = 60
    LITELLM_GATEWAY_URL: str = ""
    LITELLM_API_KEY: str = ""
    LITELLM_MODEL: str = ""
    LITELLM_TIMEOUT: int = 60
    OLLAMA_URL: str = "http://localhost:11434/api"
    OLLAMA_TIMEOUT: int = 600
    OLLAMA_KEEP_ALIVE: str = "30m"
    OLLAMA_NUM_BATCH: int = OLLAMA_BATCH_POLICY.default
    OLLAMA_CODING_NUM_CTX: int = 8192
    OLLAMA_CONTEXT_MAX_CHARS: int = 12000
    OLLAMA_STREAM_MAX_BUFFER_CHARS: int = 1_000_000
    CODING_MODEL: str = "qwen2.5-coder:7b"
    REDIS_MAX_CONNECTIONS: int = 50
    SEMANTIC_CACHE_TTL: int = 3600
    SEMANTIC_CACHE_MAX_ITEMS: int = 500
    SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD: int = 3
    SEMANTIC_CACHE_REDIS_CB_COOLDOWN_SECONDS: int = 30


def load_llm_settings(*, env_path: Path, skip_default_dotenv: bool) -> LLMClientSettings:
    """Load LLM settings with the same dotenv precedence as the config facade."""
    env_file = str(env_path) if env_path.exists() and not skip_default_dotenv else None
    if env_file is None:
        return LLMClientSettings()

    scoped_settings_type: type[LLMClientSettings] = type(
        "ScopedLLMClientSettings",
        (LLMClientSettings,),
        {
            "__module__": __name__,
            "model_config": SettingsConfigDict(
                env_file=env_file, env_file_encoding="utf-8", extra="ignore"
            ),
        },
    )
    return scoped_settings_type()
