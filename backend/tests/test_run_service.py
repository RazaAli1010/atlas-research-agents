"""RunService lifecycle: start pauses, resume completes, runs row stays in sync.

A shared ``MemorySaver`` is injected so state persists across the separate
``start``/``resume`` calls (each builds its own graph, as it would across a restart).
Async methods are driven with ``asyncio.run`` — no pytest-asyncio dependency.
"""

import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes import writer as writer_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import Review, SectionPlan
from app.persistence.runs_repo import RunsRepo
from app.services.run_service import RunService
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


def _service(tmp_path: Path) -> RunService:
    repo = RunsRepo(db_path=str(tmp_path / "runs.sqlite"))
    saver = MemorySaver()

    @contextmanager
    def shared_cx():
        yield saver

    return RunService(repo, checkpointer_cx=shared_cx)


def test_start_pauses_and_records_awaiting_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch)
    service = _service(tmp_path)

    result = asyncio.run(service.start("Compare vector DBs"))

    assert result.status == "awaiting_approval"
    assert result.run_id != result.thread_id  # distinct ids
    assert result.interrupt_plan is not None
    assert len(result.interrupt_plan) == 2
    assert result.interrupt_plan[0]["id"] == "s1"

    row = service._repo.get(result.run_id)
    assert row is not None
    assert row.status == "awaiting_approval"


def test_resume_completes_and_populates_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch)
    service = _service(tmp_path)

    started = asyncio.run(service.start("Compare vector DBs"))
    row = asyncio.run(service.resume(started.run_id, {"action": "approve"}))

    # Full lifecycle: planning (create) -> awaiting_approval (start) -> done (resume).
    assert row.status == "done"
    assert row.report_md is not None and row.report_md.strip()
    assert row.cost_usd > 0


def test_resume_unknown_run_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch)
    service = _service(tmp_path)
    with pytest.raises(KeyError):
        asyncio.run(service.resume("missing", {"action": "approve"}))
