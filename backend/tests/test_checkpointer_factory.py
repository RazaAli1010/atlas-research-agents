"""The checkpointer factory selects sqlite by config and drives a real run."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import ResearchState, Review, SectionPlan
from app.persistence import checkpointer as cp_mod
from app.persistence.checkpointer import checkpointer_cx
from tests.fakes import FakeModel, FakeReviewModel, ai


class _FakeStructuredModel:
    def invoke(self, _messages: object) -> dict:
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            response_metadata={"model_name": "gpt-4o-mini"},
        )
        section = SectionPlan(id="x", title="Overview", objective="obj", suggested_queries=["q"])
        return {"parsed": PlannerOutput(sections=[section]), "raw": raw}


class _FakeModel:
    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        return _FakeStructuredModel()


def _seed() -> ResearchState:
    return {
        "topic": "T",
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "status": "planning",
    }


def test_sqlite_backend_yields_saver_and_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cp_mod.settings, "CHECKPOINT_BACKEND", "sqlite")
    monkeypatch.setattr(cp_mod, "SQLITE_PATH", str(tmp_path / "cp.sqlite"))
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _FakeModel())
    # Topology now includes the worker; keep it offline.
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body.")]))
    approve = Review(section_id="x", verdict="approved", score=0.95, feedback="")
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: FakeReviewModel([approve]))

    config = {"configurable": {"thread_id": "t1"}}
    with checkpointer_cx() as cp:
        assert isinstance(cp, SqliteSaver)
        graph = build_graph(cp)
        graph.invoke(_seed(), config=config)  # pauses at approval
        final = graph.invoke(Command(resume={"action": "approve"}), config=config)

    assert final["status"] == "done"
    assert final["final_report_md"].startswith("# T")
