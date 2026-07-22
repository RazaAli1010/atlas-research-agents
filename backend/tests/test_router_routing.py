"""Per-role routing in get_model (F9).

``init_chat_model`` is monkeypatched to capture the model-id argument, so no real
client is built and no network/key is needed. The per-role cache is cleared with
``_reset_models`` between cases, and ``router.settings.MODEL_ROUTING`` is patched to
drive each scenario.
"""

import pytest

from app.config import settings
from app.llm import router


class _FakeModel:
    """Stand-in for a BaseChatModel that just remembers the id it was built from."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id


@pytest.fixture
def capture_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace init_chat_model with a fake that records the model id, and reset cache."""

    def _fake_init(model_id: str, **_kwargs: object) -> _FakeModel:
        return _FakeModel(model_id)

    monkeypatch.setattr(router, "init_chat_model", _fake_init)
    router._reset_models()


def test_routing_maps_roles_to_configured_models(
    monkeypatch: pytest.MonkeyPatch, capture_init: None
) -> None:
    monkeypatch.setattr(
        settings,
        "MODEL_ROUTING",
        {
            "planner": "openai:gpt-4o",
            "reviewer": "openai:gpt-4o",
            "writer": "openai:gpt-4o",
            "worker": "openai:gpt-4o-mini",
        },
    )

    planner = router.get_model("planner")
    worker = router.get_model("worker")

    assert planner.model_id == "openai:gpt-4o"  # type: ignore[attr-defined]
    assert worker.model_id == "openai:gpt-4o-mini"  # type: ignore[attr-defined]


def test_partial_routing_falls_back_to_default_model(
    monkeypatch: pytest.MonkeyPatch, capture_init: None
) -> None:
    monkeypatch.setattr(settings, "MODEL_ROUTING", {"planner": "openai:gpt-4o"})
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "openai:gpt-4o-mini")

    worker = router.get_model("worker")

    assert worker.model_id == "openai:gpt-4o-mini"  # type: ignore[attr-defined]


def test_get_model_caches_per_role(
    monkeypatch: pytest.MonkeyPatch, capture_init: None
) -> None:
    monkeypatch.setattr(settings, "MODEL_ROUTING", {"planner": "openai:gpt-4o"})

    assert router.get_model("planner") is router.get_model("planner")


def test_get_model_rejects_unknown_role(capture_init: None) -> None:
    with pytest.raises(ValueError, match="unknown role"):
        router.get_model("nope")  # type: ignore[arg-type]
