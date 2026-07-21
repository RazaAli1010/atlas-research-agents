"""End-to-end skeleton: planner -> writer produces a report and logs usage."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import ResearchState, SectionPlan


class _FakeStructuredModel:
    def invoke(self, _messages: object) -> dict:
        sections = [
            SectionPlan(id="x", title="Pricing", objective="Compare", suggested_queries=["q"]),
            SectionPlan(id="y", title="Scalability", objective="Assess", suggested_queries=["q"]),
        ]
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            response_metadata={"model_name": "gpt-4o-mini"},
        )
        return {"parsed": PlannerOutput(sections=sections), "raw": raw}


class _FakeModel:
    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        return _FakeStructuredModel()


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


def test_graph_runs_with_memory_saver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakeModel())

    graph = build_graph(MemorySaver())
    topic = "Compare vector database pricing for a startup"
    final = graph.invoke(_seed(topic), config={"configurable": {"thread_id": "t1"}})

    assert final["status"] == "done"
    assert final["final_report_md"].startswith(f"# {topic}")
    assert "Pricing" in final["final_report_md"]
    assert "Scalability" in final["final_report_md"]
    assert len(final["usage_log"]) >= 1
