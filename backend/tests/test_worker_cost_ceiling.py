"""When accrued cost >= RUN_COST_CEILING_USD the worker skips tools and flags the draft."""

import pytest

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import RUN_COST_CEILING_USD, SectionPlan, UsageEvent
from tests.fakes import CountingTool, FakeModel, ai, tool_call


def test_cost_ceiling_skips_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = CountingTool(name="web_search")
    # Even though the model asks for a tool, the ceiling must prevent execution.
    tc = [tool_call("web_search", {"query": "q"})]
    model = FakeModel([ai(content="Draft from context.", tool_calls=tc)])

    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [counter])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: model)

    over_budget = [
        UsageEvent(
            node="planner",
            model="m",
            input_tokens=1,
            output_tokens=1,
            cost_usd=RUN_COST_CEILING_USD,
        )
    ]
    section = SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])
    out = worker({"section": section, "topic": "T", "usage_log": over_budget})

    assert counter.count == 0  # no tool calls made
    draft = out["drafts"][0]
    assert "cost ceiling reached" in draft.content_md
    assert draft.sources == []
