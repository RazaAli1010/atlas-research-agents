"""Planner clamps to MAX_SECTIONS, re-ids sequentially, and logs usage.

The model is mocked so the test is deterministic and offline: it returns 7
sections which must be clamped to 6, re-ided s1..s6.
"""

import pytest
from langchain_core.messages import AIMessage

from app.graph.nodes import planner as planner_mod
from app.graph.nodes.planner import PlannerOutput, planner
from app.graph.state import SectionPlan


def _sections(n: int) -> list[SectionPlan]:
    return [
        SectionPlan(id=f"orig{i}", title=f"Title {i}", objective="obj", suggested_queries=["q"])
        for i in range(1, n + 1)
    ]


class _FakeStructuredModel:
    def invoke(self, _messages: object) -> dict:
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_metadata={"model_name": "gpt-4o-mini-2024-07-18"},
        )
        return {"parsed": PlannerOutput(sections=_sections(7)), "raw": raw}


class _FakeModel:
    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        assert include_raw is True  # required so usage_metadata is reachable
        return _FakeStructuredModel()


def test_planner_clamps_and_reids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakeModel())

    out = planner({"topic": "anything"})  # type: ignore[typeddict-item]

    assert len(out["plan"]) == 6  # MAX_SECTIONS, clamped from 7
    assert [s.id for s in out["plan"]] == [f"s{i}" for i in range(1, 7)]
    assert out["status"] == "awaiting_approval"


def test_planner_logs_one_usage_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakeModel())

    out = planner({"topic": "anything"})  # type: ignore[typeddict-item]

    assert len(out["usage_log"]) == 1
    event = out["usage_log"][0]
    assert event.node == "planner"
    assert event.input_tokens == 100
    assert event.cost_usd > 0
