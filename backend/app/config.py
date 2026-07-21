"""Application configuration via pydantic-settings (12-factor, env-driven).

Required keys have no default and fail fast at construction if missing.
Optional keys carry sensible defaults. See `.env.example` for the full list.
"""

from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- required — missing → ValidationError at construction (fail fast) ---
    OPENAI_API_KEY: str
    TAVILY_API_KEY: str

    # --- optional ---
    # Default chat model for all roles (provider-prefixed for init_chat_model).
    # OpenAI is the sole provider (§3). F9 replaces the router's role->model logic;
    # this default stays as the fallback.
    DEFAULT_MODEL: str = "openai:gpt-4o-mini"
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = "atlas"
    DATABASE_URL: str = "postgresql://atlas:atlas@localhost:5432/atlas"
    CHECKPOINT_BACKEND: Literal["sqlite", "postgres"] = "sqlite"
    # NoDecode disables pydantic-settings' source-level JSON decoding of this
    # complex field, so the validator below receives the raw string and can
    # split it on commas.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Accept a comma-separated string for CORS_ORIGINS.

        Without NoDecode, pydantic-settings attempts JSON decoding of the env
        value, so ``CORS_ORIGINS=http://localhost:5173`` (non-JSON) would raise.
        Splitting on commas here keeps the typed field a ``list[str]``.
        """
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


def get_settings() -> Settings:
    """Construct a fresh Settings instance (used by tests to control the env)."""
    return Settings()


# Module-level singleton for application use.
settings = get_settings()
