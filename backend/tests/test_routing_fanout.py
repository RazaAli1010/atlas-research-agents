"""fan_out emits one Send('worker', ...) per planned section."""

from app.graph.routing import fan_out
from app.graph.state import SectionPlan


def _plan(n: int) -> list[SectionPlan]:
    return [
        SectionPlan(id=f"s{i}", title=f"Title {i}", objective="obj", suggested_queries=["q"])
        for i in range(1, n + 1)
    ]


def test_fan_out_one_send_per_section() -> None:
    state = {"topic": "Vector DB pricing", "plan": _plan(4), "usage_log": []}

    sends = fan_out(state)  # type: ignore[arg-type]

    assert len(sends) == 4
    assert all(s.node == "worker" for s in sends)
    assert [s.arg["section"].id for s in sends] == ["s1", "s2", "s3", "s4"]
    assert all(s.arg["topic"] == "Vector DB pricing" for s in sends)
    # usage_log snapshot is carried so the worker can enforce the cost ceiling.
    assert all("usage_log" in s.arg for s in sends)
