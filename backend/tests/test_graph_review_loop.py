"""Termination guarantee: an always-revise reviewer still halts within budget."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import MAX_REVISIONS_PER_SECTION, ResearchState, Review, SectionPlan
from tests.fakes import FakeModel, FakeReviewModel, ai


class _FakePlanModel:
    """Structured-output planner fake producing a single section."""

    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        return self

    def invoke(self, _messages: object) -> dict:
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            response_metadata={"model_name": "gpt-4o-mini"},
        )
        sections = [SectionPlan(id="x", title="Pricing", objective="o", suggested_queries=["q"])]
        return {"parsed": PlannerOutput(sections=sections), "raw": raw}


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


def test_always_revise_loop_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakePlanModel())
    # Stub worker: no tools, one-line body; each revision bumps the draft revision.
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body.")]))
    # Reviewer always says revise (score < 0.7). Single section → calls == passes.
    review = Review(section_id="x", verdict="revise", score=0.3, feedback="do better")
    fake_reviewer = FakeReviewModel([review])
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: fake_reviewer)

    graph = build_graph(MemorySaver())
    final = graph.invoke(_seed("Hard topic"), config={"configurable": {"thread_id": "loop1"}})

    # Terminates at the writer despite always-revise.
    assert final["status"] == "done"
    # Bounded: at most 1 initial + MAX_REVISIONS_PER_SECTION reviewer passes.
    assert fake_reviewer.calls <= 1 + MAX_REVISIONS_PER_SECTION
    # Full budget used for the failing section.
    assert final["revision_counts"]["s1"] == MAX_REVISIONS_PER_SECTION
    # The unapproved section triggers the Limitations note.
    assert "**Limitations:**" in final["final_report_md"]
