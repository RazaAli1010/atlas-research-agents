"""Settings behaviour: defaults, CORS parsing, and fail-fast on missing keys.

Each test constructs ``Settings`` directly with ``_env_file=None`` so a stray local
``backend/.env`` can't leak in and mask the behaviour under test.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CHECKPOINT_BACKEND", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.CHECKPOINT_BACKEND == "sqlite"
    assert settings.CORS_ORIGINS == ["http://localhost:5173"]
    assert settings.LANGSMITH_PROJECT == "atlas"
    assert settings.LANGSMITH_TRACING is False


def test_cors_origins_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_missing_required_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "OPENAI_API_KEY" in str(excinfo.value)
