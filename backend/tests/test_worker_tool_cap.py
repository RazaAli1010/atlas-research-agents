"""The worker never exceeds MAX_TOOL_CALLS_PER_WORKER tool invocations."""

import pytest

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import MAX_TOOL_CALLS_PER_WORKER, SectionPlan
from tests.fakes import CountingTool, FakeModel, ai, tool_call


def test_tool_call_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = CountingTool(name="web_search")
    # Model requests a tool on every turn — the loop must stop at the budget.
    always_tool = ai(content="", tool_calls=[tool_call("web_search", {"query": "q"})])

    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [counter])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([always_tool]))

    section = SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])
    out = worker({"section": section, "topic": "T", "usage_log": []})

    assert counter.count == MAX_TOOL_CALLS_PER_WORKER  # capped, not exceeded
    assert len(out["drafts"]) == 1  # a draft is still produced
