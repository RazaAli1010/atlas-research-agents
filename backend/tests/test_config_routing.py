"""MODEL_ROUTING config parsing + unknown-role rejection (F9).

Each test constructs ``Settings`` directly with ``_env_file=None`` so a stray local
``backend/.env`` can't leak in and mask the behaviour under test (matches test_config.py).
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")


def test_default_routing_maps_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("MODEL_ROUTING", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.MODEL_ROUTING["worker"] == "openai:gpt-4o-mini"
    assert settings.MODEL_ROUTING["planner"] == "openai:gpt-4o"


def test_routing_json_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv(
        "MODEL_ROUTING",
        '{"planner":"openai:gpt-4o","worker":"openai:gpt-4o-mini"}',
    )

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.MODEL_ROUTING == {
        "planner": "openai:gpt-4o",
        "worker": "openai:gpt-4o-mini",
    }


def test_unknown_role_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("MODEL_ROUTING", '{"bogus":"openai:gpt-4o"}')

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "bogus" in str(excinfo.value)
