"""Durability proof: resume survives a simulated process restart.

A run is interrupted with one graph object over a SqliteSaver file; that saver is
closed (process death). A *fresh* saver + graph over the same file then resumes the
same ``thread_id`` to completion — proving the pause state lives in the checkpoint
store, not the process.
"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph.builder import build_graph
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes import writer as writer_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import ResearchState, Review, SectionPlan
from tests.fakes import FakeModel, FakeReviewModel, ai

_APPROVE = Review(section_id="x", verdict="approved", score=0.95, feedback="")


class _PlannerFake:
    def with_structured_output(self, _schema: object, include_raw: bool = False) -> object:
        class _Structured:
            def invoke(self, _messages: object) -> dict:
                sections = [
                    SectionPlan(id="a", title="Pricing", objective="C", suggested_queries=["q"]),
                    SectionPlan(id="b", title="Scale", objective="A", suggested_queries=["q"]),
                ]
                raw = AIMessage(
                    content="",
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    response_metadata={"model_name": "gpt-4o-mini"},
                )
                return {"parsed": PlannerOutput(sections=sections), "raw": raw}

        return _Structured()


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _PlannerFake())
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body.")]))
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: FakeReviewModel([_APPROVE]))
    monkeypatch.setattr(
        writer_mod, "get_model", lambda _role: FakeModel([ai(content="Executive summary.")])
    )


def _seed() -> ResearchState:
    return {
        "topic": "topic",
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "status": "planning",
    }


def test_resume_survives_process_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch)
    db = str(tmp_path / "cp.sqlite")
    config = {"configurable": {"thread_id": "restart"}}

    # --- process 1: run to the interrupt, then "die" (close the saver) ---
    with SqliteSaver.from_conn_string(db) as cp1:
        cp1.setup()
        graph1 = build_graph(cp1)
        graph1.invoke(_seed(), config=config)
        assert graph1.get_state(config).interrupts  # paused

    # --- process 2: fresh saver + graph over the SAME file, resume ---
    with SqliteSaver.from_conn_string(db) as cp2:
        cp2.setup()
        graph2 = build_graph(cp2)
        graph2.invoke(Command(resume={"action": "approve"}), config=config)
        snap = graph2.get_state(config)

    assert snap.values["status"] == "done"
    assert snap.values["final_report_md"]
