"""Environment-driven configuration. Secrets are never hardcoded."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.exceptions import MissingAPIKeyError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE, override=True)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        protected_namespaces=("settings_",),
    )

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_reasoning_effort: str = Field(default="low", alias="GROQ_REASONING_EFFORT")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_primary_provider: str = Field(default="groq", alias="LLM_PRIMARY_PROVIDER")
    llm_fallback_provider: str = Field(default="ollama", alias="LLM_FALLBACK_PROVIDER")
    llm_fallback_enabled: bool = Field(default=True, alias="LLM_FALLBACK_ENABLED")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma3:12b", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=120.0, alias="OLLAMA_TIMEOUT_SECONDS")
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_required: bool = Field(default=False, alias="SUPABASE_REQUIRED")

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def strip_key(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip().strip("'\"")

    @field_validator("llm_primary_provider")
    @classmethod
    def validate_primary_provider(cls, value: str) -> str:
        if str(value).strip().lower() != "groq":
            raise ValueError("LLM_PRIMARY_PROVIDER must be groq.")
        return "groq"

    @field_validator("groq_reasoning_effort")
    @classmethod
    def validate_groq_reasoning_effort(cls, value: str) -> str:
        candidate = str(value).strip().lower()
        if candidate not in {"low", "medium", "high"}:
            raise ValueError("GROQ_REASONING_EFFORT must be low, medium, or high.")
        return candidate

    @field_validator("llm_fallback_provider")
    @classmethod
    def validate_fallback_provider(cls, value: str) -> str:
        if str(value).strip().lower() != "ollama":
            raise ValueError("LLM_FALLBACK_PROVIDER must be ollama.")
        return "ollama"

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        candidate = str(value).strip().rstrip("/")
        parsed = urlparse(candidate)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must use local http://localhost or 127.0.0.1.")
        return candidate

    def require_api_key(self) -> str:
        """Return the API key or fail with a clear configuration error."""
        if not self.groq_api_key:
            raise MissingAPIKeyError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add a Groq "
                "key. Do not commit .env or paste keys into source."
            )
        return self.groq_api_key

    @property
    def has_api_key(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance. Call get_settings.cache_clear() in tests if needed."""
    return Settings()
