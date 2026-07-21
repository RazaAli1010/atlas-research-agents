"""Integration tests for the approval interrupt over a MemorySaver.

Proves the graph pauses at ``approval_gate`` with the plan payload, resumes to a
finished report on ``approve``, and honors an edited plan in the fan-out.
"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import ResearchState, Review, SectionPlan
from tests.fakes import FakeModel, FakeReviewModel, ai

_APPROVE = Review(section_id="x", verdict="approved", score=0.95, feedback="")


class _PlannerFake:
    """Structured-output planner fake yielding ``n`` sections."""

    def __init__(self, n: int) -> None:
        self._n = n

    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        n = self._n

        class _Structured:
            def invoke(self, _messages: object) -> dict:
                sections = [
                    SectionPlan(
                        id=f"x{i}",
                        title=f"Section {i}",
                        objective=f"Answer {i}",
                        suggested_queries=["q"],
                    )
                    for i in range(1, n + 1)
                ]
                raw = AIMessage(
                    content="",
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    response_metadata={"model_name": "gpt-4o-mini"},
                )
                return {"parsed": PlannerOutput(sections=sections), "raw": raw}

        return _Structured()


def _patch_nodes(monkeypatch: pytest.MonkeyPatch, n_sections: int) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _PlannerFake(n_sections))
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body.")]))
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: FakeReviewModel([_APPROVE]))


def _seed(topic: str) -> ResearchState:
    return {
        "topic": topic,
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "status": "planning",
    }


def test_graph_pauses_at_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nodes(monkeypatch, n_sections=2)
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "pause"}}

    graph.invoke(_seed("topic"), config=config)
    snap = graph.get_state(config)

    assert snap.next == ("approval_gate",)
    assert snap.interrupts, "expected a pending interrupt"
    assert snap.values["status"] == "awaiting_approval"
    plan = snap.interrupts[0].value["plan"]
    assert len(plan) == 2
    assert plan[0]["id"] == "s1"  # planner re-ids sequentially


def test_resume_approve_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nodes(monkeypatch, n_sections=2)
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "approve"}}

    graph.invoke(_seed("topic"), config=config)
    graph.invoke(Command(resume={"action": "approve"}), config=config)
    snap = graph.get_state(config)

    assert snap.values["status"] == "done"
    assert snap.values["final_report_md"]
    assert len(snap.values["drafts"]) == 2  # one draft per approved section


def test_edit_changes_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nodes(monkeypatch, n_sections=3)  # planner proposes 3
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "edit"}}

    graph.invoke(_seed("topic"), config=config)
    proposed = graph.get_state(config).interrupts[0].value["plan"]
    edited = proposed[:2]  # human keeps only 2

    graph.invoke(Command(resume={"action": "edit", "plan": edited}), config=config)
    snap = graph.get_state(config)

    assert snap.values["status"] == "done"
    assert len(snap.values["drafts"]) == 2  # fan-out honored the edited plan, not 3
