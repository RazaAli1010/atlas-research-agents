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
    # OpenAI is the sole provider (§3). Used by the router as the per-role fallback
    # when a role is absent from MODEL_ROUTING.
    DEFAULT_MODEL: str = "openai:gpt-4o-mini"
    # Role -> model routing (F9). Maps each graph role to a provider-prefixed model
    # id for init_chat_model. Strong tier (gpt-4o) for planner/reviewer/writer, cheap
    # tier (gpt-4o-mini) for the fan-out worker. Override via env with a JSON object,
    # e.g. MODEL_ROUTING='{"worker":"openai:gpt-4o"}' (pydantic-settings JSON-decodes
    # a dict field automatically). Roles omitted here fall back to DEFAULT_MODEL.
    MODEL_ROUTING: dict[str, str] = {
        "planner": "openai:gpt-4o",
        "reviewer": "openai:gpt-4o",
        "writer": "openai:gpt-4o",
        "worker": "openai:gpt-4o-mini",
    }
    # Eval harness judge models (F8). Strong judge for coverage/groundedness;
    # cheap judge used by `run_benchmark.py --smoke`. Not used by graph nodes.
    EVAL_JUDGE_MODEL: str = "openai:gpt-4o"
    EVAL_SMOKE_MODEL: str = "openai:gpt-4o-mini"
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = "atlas"
    DATABASE_URL: str = "postgresql://atlas:atlas@localhost:5432/atlas"
    CHECKPOINT_BACKEND: Literal["sqlite", "postgres"] = "sqlite"
    # Base URL of the user's existing RAG service. Unset → the rag_search tool
    # self-disables (not registered) and the graph runs without it (F3).
    RAG_SERVICE_URL: str | None = None
    # NoDecode disables pydantic-settings' source-level JSON decoding of this
    # complex field, so the validator below receives the raw string and can
    # split it on commas.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("MODEL_ROUTING")
    @classmethod
    def _known_roles_only(cls, v: dict[str, str]) -> dict[str, str]:
        """Reject unknown role keys so a typo in MODEL_ROUTING fails fast at startup.

        Partial maps are allowed — any of the four roles may be omitted and will fall
        back to DEFAULT_MODEL in the router — but a key outside the role set is an error.
        """
        valid = {"planner", "worker", "reviewer", "writer"}
        bad = set(v) - valid
        if bad:
            raise ValueError(f"unknown role(s) in MODEL_ROUTING: {sorted(bad)}")
        return v

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
