"""The worker records one ToolCallRecord per tool invocation into state (F8, Delta 1).

This is the independent tool-result trace the anti-fabrication grader trusts and the
source of the "tool calls per section" trajectory stat.
"""

import pytest

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import SectionPlan
from tests.fakes import CountingTool, FakeModel, ai, tool_call


def test_worker_records_one_toolcall_per_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = CountingTool(name="web_search")  # returns [{"url": "https://example.com/a", ...}]
    # First turn requests two web_search calls; second turn returns prose and stops.
    first = ai(
        content="",
        tool_calls=[
            tool_call("web_search", {"query": "q1"}, "c1"),
            tool_call("web_search", {"query": "q2"}, "c2"),
        ],
    )
    stop = ai(content="Body [1].")

    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [counter])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([first, stop]))

    section = SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])
    out = worker({"section": section, "topic": "T", "usage_log": []})

    records = out["tool_calls"]
    assert counter.count == 2  # two invocations
    assert len(records) == 2  # one record each
    for record in records:
        assert record.section_id == "s1"
        assert record.tool == "web_search"
        assert record.urls == ["https://example.com/a"]  # the URL the tool returned


def test_worker_records_empty_urls_for_no_result_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyTool:
        name = "web_search"

        def invoke(self, _args: dict) -> list:
            return []  # graceful no-results path

    tool = EmptyTool()
    first = ai(content="", tool_calls=[tool_call("web_search", {"query": "q"}, "c1")])
    stop = ai(content="Body.")

    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [tool])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([first, stop]))

    section = SectionPlan(id="s2", title="T", objective="o", suggested_queries=["q"])
    out = worker({"section": section, "topic": "T", "usage_log": []})

    assert len(out["tool_calls"]) == 1
    assert out["tool_calls"][0].urls == []  # no URLs, but the call is still recorded
