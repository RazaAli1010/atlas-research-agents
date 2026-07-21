"""Unit tests for approval_gate — the researching transition, edit, and clamp.

These call the node directly with a resume ``decision`` (the value ``interrupt()``
returns on resume), so no checkpointer/graph is needed. Covers the ``researching``
status transition deterministically for the acceptance criteria.
"""

from app.graph.nodes.approval import approval_gate
from app.graph.state import MAX_SECTIONS, ResearchState, SectionPlan


def _section(i: int) -> dict:
    return {
        "id": f"s{i}",
        "title": f"Section {i}",
        "objective": f"Answer {i}",
        "suggested_queries": ["q"],
    }


def _state_with(n: int) -> ResearchState:
    plan = [SectionPlan(**_section(i)) for i in range(1, n + 1)]
    return {
        "topic": "t",
        "plan": plan,
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "status": "awaiting_approval",
    }


def test_approve_marks_researching_without_touching_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.graph.nodes.approval.interrupt", lambda _payload: {"action": "approve"}
    )
    out = approval_gate(_state_with(3))
    assert out == {"plan_approved": True, "status": "researching"}
    assert "plan" not in out  # plan left as-is
    assert "usage_log" not in out  # no model call → no usage


def test_edit_replaces_plan(monkeypatch) -> None:
    edited = [_section(1), _section(2)]
    monkeypatch.setattr(
        "app.graph.nodes.approval.interrupt",
        lambda _payload: {"action": "edit", "plan": edited},
    )
    out = approval_gate(_state_with(4))
    assert out["status"] == "researching"
    assert out["plan_approved"] is True
    assert [s.id for s in out["plan"]] == ["s1", "s2"]


def test_edit_clamps_to_max_sections(monkeypatch) -> None:
    oversized = [_section(i) for i in range(1, MAX_SECTIONS + 2)]  # 7 sections
    monkeypatch.setattr(
        "app.graph.nodes.approval.interrupt",
        lambda _payload: {"action": "edit", "plan": oversized},
    )
    out = approval_gate(_state_with(1))
    assert len(out["plan"]) == MAX_SECTIONS
