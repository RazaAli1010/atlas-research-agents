"""Pure translation from LangGraph stream chunks to AtlasEvents (F6).

No server, no graph — synthetic ``(mode, data)`` chunks fed straight to the translators.
The writer-token case proves the ``messages`` plumbing even though the deterministic F3
writer emits none at runtime.
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk

from app.api.sse import (
    CostAccumulator,
    DoneEvent,
    InterruptEvent,
    NodeFinishedEvent,
    NodeStartedEvent,
    ReviewEvent,
    StatusEvent,
    TokenEvent,
    UsageEventMsg,
    chunk_to_events,
    terminal_events,
)
from app.graph.state import Review, SectionDraft, SectionPlan, UsageEvent

_USAGE = UsageEvent(
    node="planner", model="gpt-4o-mini", input_tokens=10, output_tokens=5, cost_usd=0.02
)


def test_task_start_yields_node_started() -> None:
    events = chunk_to_events(
        "tasks", {"name": "planner", "input": {}, "triggers": ["start"]}, CostAccumulator()
    )
    assert len(events) == 1
    assert isinstance(events[0], NodeStartedEvent)
    assert events[0].node == "planner"


def test_planner_result_orders_status_usage_finished_and_advances_cost() -> None:
    cost = CostAccumulator()
    events = chunk_to_events(
        "tasks",
        {
            "name": "planner",
            "result": {"status": "awaiting_approval", "usage_log": [_USAGE]},
            "interrupts": [],
        },
        cost,
    )
    assert [type(e) for e in events] == [StatusEvent, UsageEventMsg, NodeFinishedEvent]
    assert events[0].status == "awaiting_approval"
    assert events[1].total_cost_usd == 0.02  # accumulator advanced
    assert cost.total == 0.02


def test_reviewer_result_emits_review_and_usage() -> None:
    review = Review(section_id="s1", verdict="revise", score=0.4, feedback="fix it")
    events = chunk_to_events(
        "tasks",
        {
            "name": "reviewer",
            "result": {"status": "reviewing", "reviews": [review], "usage_log": [_USAGE]},
            "interrupts": [],
        },
        CostAccumulator(),
    )
    kinds = [type(e) for e in events]
    assert ReviewEvent in kinds and UsageEventMsg in kinds
    review_ev = next(e for e in events if isinstance(e, ReviewEvent))
    assert review_ev.review.section_id == "s1"


def test_worker_task_carries_section_id() -> None:
    section = SectionPlan(id="s2", title="T", objective="O", suggested_queries=["q"])
    start_chunk = {"name": "worker", "input": {"section": section}, "triggers": []}
    start = chunk_to_events("tasks", start_chunk, CostAccumulator())
    assert isinstance(start[0], NodeStartedEvent) and start[0].section_id == "s2"

    draft = SectionDraft(section_id="s2", content_md="body", sources=[], revision=0)
    finish_chunk = {"name": "worker", "result": {"drafts": [draft]}, "interrupts": []}
    finish = chunk_to_events("tasks", finish_chunk, CostAccumulator())
    fin = next(e for e in finish if isinstance(e, NodeFinishedEvent))
    assert fin.section_id == "s2"


def test_writer_message_chunk_becomes_token_but_other_nodes_do_not() -> None:
    writer_chunk = ("messages", (AIMessageChunk(content="he"), {"langgraph_node": "writer"}))
    events = chunk_to_events(*writer_chunk, cost=CostAccumulator())
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].delta == "he"

    reviewer_chunk = (AIMessageChunk(content="he"), {"langgraph_node": "reviewer"})
    other = chunk_to_events("messages", reviewer_chunk, CostAccumulator())
    assert other == []


def test_terminal_events_interrupt_then_done() -> None:
    plan = [{"id": "s1", "title": "T", "objective": "O", "suggested_queries": ["q"]}]
    paused = SimpleNamespace(interrupts=[SimpleNamespace(value={"plan": plan})], values={})
    ev = terminal_events(paused)
    assert len(ev) == 1 and isinstance(ev[0], InterruptEvent)
    assert ev[0].payload.plan[0].id == "s1"

    finished = SimpleNamespace(interrupts=[], values={"final_report_md": "# Report"})
    done = terminal_events(finished)
    assert len(done) == 1 and isinstance(done[0], DoneEvent)
    assert done[0].report_md == "# Report"

    empty = SimpleNamespace(interrupts=[], values={"final_report_md": ""})
    assert terminal_events(empty) == []
