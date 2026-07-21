"""AtlasEvent Pydantic mirror + serializer round-trip (F6 acceptance).

Every event variant must validate against the discriminated union and serialize to an
sse-starlette frame whose ``event`` is the type and whose ``data`` is the event JSON.
"""

import json

from app.api.sse import (
    AtlasEventAdapter,
    DoneEvent,
    ErrorEvent,
    InterruptEvent,
    InterruptPayload,
    NodeFinishedEvent,
    NodeStartedEvent,
    ReviewEvent,
    StatusEvent,
    TokenEvent,
    UsageEventMsg,
    to_sse,
)
from app.graph.state import Review, SectionPlan, UsageEvent

_PLAN = [SectionPlan(id="s1", title="T", objective="O", suggested_queries=["q"])]
_USAGE = UsageEvent(
    node="planner", model="gpt-4o-mini", input_tokens=10, output_tokens=5, cost_usd=0.01
)
_REVIEW = Review(section_id="s1", verdict="approved", score=0.9, feedback="")

_EVENTS = [
    StatusEvent(status="planning"),
    NodeStartedEvent(node="planner"),
    NodeFinishedEvent(node="planner", summary="Planned 1 sections"),
    TokenEvent(node="writer", delta="he"),
    InterruptEvent(payload=InterruptPayload(plan=_PLAN)),
    UsageEventMsg(event=_USAGE, total_cost_usd=0.01),
    ReviewEvent(review=_REVIEW),
    DoneEvent(report_md="# Report"),
    ErrorEvent(message="boom"),
]


def test_every_variant_round_trips_through_the_union() -> None:
    for ev in _EVENTS:
        restored = AtlasEventAdapter.validate_python(ev.model_dump())
        assert type(restored) is type(ev)
        assert restored.type == ev.type  # type: ignore[attr-defined]


def test_to_sse_frames_carry_type_as_event_and_json_data() -> None:
    for ev in _EVENTS:
        frame = to_sse(ev)
        assert frame["event"] == ev.type  # type: ignore[attr-defined]
        parsed = json.loads(frame["data"])
        assert parsed["type"] == ev.type  # type: ignore[attr-defined]


def test_discriminator_selects_the_right_class() -> None:
    restored = AtlasEventAdapter.validate_python(
        {"type": "usage", "event": _USAGE.model_dump(), "total_cost_usd": 0.25}
    )
    assert isinstance(restored, UsageEventMsg)
    assert restored.total_cost_usd == 0.25
