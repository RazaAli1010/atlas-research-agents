"""Every tool_call in a multi-call message is answered, even at the budget boundary.

Regression for the OpenAI 400 ("assistant message with 'tool_calls' must be followed by
tool messages responding to each 'tool_call_id'") that occurred when the tool-call budget
was hit partway through a single message's batch of parallel tool calls. Real models emit
several tool calls per message; the old code broke mid-batch and left some unanswered.
"""

import pytest

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import MAX_TOOL_CALLS_PER_WORKER, SectionPlan
from tests.fakes import CountingTool, ValidatingToolModel, ai, tool_call


def test_never_stopping_agent_at_budget_is_fully_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = CountingTool(name="web_search")
    # A model that ALWAYS requests five parallel tool calls and never voluntarily stops —
    # like a real agent that keeps calling tools past our budget (it does not know the
    # cap). Termination must come from the budget, and the budget-exhausting message plus
    # the following forced-answer turn must both leave every tool_call_id answered.
    five = ai(
        content="",
        tool_calls=[tool_call("web_search", {"query": "q"}, f"id{k}") for k in range(5)],
    )

    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [counter])
    model = ValidatingToolModel([five])  # FakeModel repeats the last response forever
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: model)

    section = SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])
    # ValidatingToolModel raises (like the real 400) if any tool_call is left unanswered.
    out = worker({"section": section, "topic": "T", "usage_log": []})

    assert counter.count == MAX_TOOL_CALLS_PER_WORKER  # executions capped at the budget
    assert len(out["drafts"]) == 1  # completes cleanly, no unanswered-tool-call error
