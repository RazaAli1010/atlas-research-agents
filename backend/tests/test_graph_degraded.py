"""End-to-end graceful degradation: no tools/sources still yields a done report."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graph import builder as builder_mod
from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import ResearchState, Review, SectionPlan
from tests.fakes import FakeModel, FakeReviewModel, ai


class _FakeStructured:
    def invoke(self, _messages: object) -> dict:
        sections = [
            SectionPlan(id="x", title="Pricing", objective="Compare", suggested_queries=["q"]),
            SectionPlan(id="y", title="Scale", objective="Assess", suggested_queries=["q"]),
        ]
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            response_metadata={"model_name": "gpt-4o-mini"},
        )
        return {"parsed": PlannerOutput(sections=sections), "raw": raw}


class _FakePlannerModel:
    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        return _FakeStructured()


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


def test_graph_completes_without_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakePlannerModel())
    # Worker: no tools available, model answers directly -> no sources gathered.
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(
        worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body without sources.")])
    )
    approve = Review(section_id="x", verdict="approved", score=0.95, feedback="")
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: FakeReviewModel([approve]))

    graph = build_graph(MemorySaver())
    final = graph.invoke(_seed("Vector DB pricing"), config={"configurable": {"thread_id": "t1"}})

    assert final["status"] == "done"
    report = final["final_report_md"]
    assert "## Sources" in report
    # Each section notes the source gap.
    assert report.count("No external sources were retrievable") == 2
    assert builder_mod is not None  # import used
