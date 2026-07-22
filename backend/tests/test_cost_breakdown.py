"""RunDetail.cost_breakdown sums usage_log cost per node (F9)."""

from app.api.routes_runs import RunDetail
from app.graph.state import UsageEvent
from app.persistence.runs_repo import RunRow


def _row() -> RunRow:
    return RunRow(
        run_id="r1",
        thread_id="t1",
        topic="anything",
        status="done",
        created_at="2026-07-22T00:00:00Z",
        cost_usd=0.0,
        report_md=None,
    )


def _usage(node: str, cost: float) -> UsageEvent:
    return UsageEvent(
        node=node, model="gpt-4o", input_tokens=0, output_tokens=0, cost_usd=cost
    )


def test_cost_breakdown_sums_per_node() -> None:
    usage_log = [
        _usage("planner", 0.10),
        _usage("worker", 0.02),
        _usage("worker", 0.03),
        _usage("writer", 0.05),
    ]

    detail = RunDetail.from_row_and_state(_row(), {"usage_log": usage_log})

    assert detail.cost_breakdown == {"planner": 0.10, "worker": 0.05, "writer": 0.05}
    assert round(sum(detail.cost_breakdown.values()), 10) == round(
        sum(e.cost_usd for e in usage_log), 10
    )


def test_cost_breakdown_empty_usage_log() -> None:
    detail = RunDetail.from_row_and_state(_row(), {})

    assert detail.cost_breakdown == {}
