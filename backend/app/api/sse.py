"""SSE event translation for ``/api/runs/{run_id}/events`` — F6.

Two responsibilities, both pure (no I/O) so they unit-test with synthetic inputs:

1. A Pydantic mirror of the frontend ``AtlasEvent`` union (SHARED CONTEXT §7) — the
   single serialization contract the SSE stream and the React client share. Each
   event serializes to one SSE frame whose ``event:`` field is the ``type`` and whose
   ``data:`` is the event JSON (:func:`to_sse`).
2. Translators from LangGraph's async stream chunks into those events
   (:func:`chunk_to_events`, :func:`terminal_events`).

We drive ``graph.astream(..., stream_mode=["tasks", "messages"])`` (LangGraph 1.x):
with a *list* of modes each item is a ``(mode, data)`` tuple.

- ``"tasks"`` emits a task-start payload (``{id, name, input, triggers, ...}``) and a
  task-result payload (``{id, name, error, interrupts, result}``) where ``result`` is
  the node's channel writes — i.e. the dict the node returned. Start → ``node_started``;
  result → ``status`` / ``review`` / ``usage`` / ``node_finished``.
- ``"messages"`` emits ``(message_chunk, metadata)`` for LLM calls inside nodes; we
  keep only the writer node's tokens (``metadata["langgraph_node"] == "writer"``).
  With the deterministic F3 writer this is dormant (no LLM there) — the plumbing lights
  up automatically once the writer becomes a streaming LLM.

``interrupt`` and ``done`` are **not** synthesized from stream payloads. They are read
authoritatively from the post-stream state snapshot (:func:`terminal_events`), reusing
the F5-proven ``graph.get_state(config).interrupts`` path — the single source of truth
for the pending plan.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.graph.state import Review, SectionPlan, UsageEvent

RunStatus = Literal[
    "planning", "awaiting_approval", "researching", "reviewing", "writing", "done", "failed"
]


# --- AtlasEvent union (mirrors SHARED CONTEXT §7) ------------------------------


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    status: RunStatus


class NodeStartedEvent(BaseModel):
    type: Literal["node_started"] = "node_started"
    node: str
    section_id: str | None = None


class NodeFinishedEvent(BaseModel):
    type: Literal["node_finished"] = "node_finished"
    node: str
    section_id: str | None = None
    summary: str


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    node: str
    delta: str


class InterruptPayload(BaseModel):
    plan: list[SectionPlan]


class InterruptEvent(BaseModel):
    type: Literal["interrupt"] = "interrupt"
    payload: InterruptPayload


class UsageEventMsg(BaseModel):
    type: Literal["usage"] = "usage"
    event: UsageEvent
    total_cost_usd: float


class ReviewEvent(BaseModel):
    type: Literal["review"] = "review"
    review: Review


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    report_md: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


AtlasEvent = Annotated[
    StatusEvent
    | NodeStartedEvent
    | NodeFinishedEvent
    | TokenEvent
    | InterruptEvent
    | UsageEventMsg
    | ReviewEvent
    | DoneEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
AtlasEventAdapter: TypeAdapter[AtlasEvent] = TypeAdapter(AtlasEvent)


def to_sse(ev: BaseModel) -> dict[str, str]:
    """Serialize one event to an sse-starlette payload: ``event: <type>``, ``data: <json>``.

    ``EventSourceResponse`` wraps a yielded ``{"event", "data"}`` dict into a frame.
    """
    return {"event": ev.type, "data": ev.model_dump_json()}  # type: ignore[attr-defined]


# --- stream-chunk translation -------------------------------------------------


class CostAccumulator:
    """Running total of ``cost_usd`` across a run, seeded from prior cost on resume."""

    def __init__(self, seed: float = 0.0) -> None:
        self.total = seed

    def add(self, cost: float) -> float:
        self.total += cost
        return self.total


def _is_task_result(data: dict[str, Any]) -> bool:
    """A ``"tasks"`` chunk is a *result* (vs a start) iff it carries result/error/interrupts."""
    return any(key in data for key in ("result", "error", "interrupts"))


def _section_id_from_task(node: str, data: dict[str, Any]) -> str | None:
    """Best-effort section id for worker task chunks (``None`` for other nodes).

    Result payload → the produced draft's ``section_id``; start payload → the ``Send``
    input's ``section`` id (a ``SectionPlan`` object or a dict, depending on timing).
    """
    if node != "worker":
        return None
    result = data.get("result")
    if isinstance(result, dict):
        drafts = result.get("drafts") or []
        if drafts:
            return getattr(drafts[0], "section_id", None)
    inp = data.get("input")
    if isinstance(inp, dict):
        section = inp.get("section")
        if section is not None:
            sid = getattr(section, "id", None)
            if sid is None and isinstance(section, dict):
                sid = section.get("id")
            return sid
    return None


def _summary(node: str, result: dict[str, Any]) -> str:
    """Human one-liner for a ``node_finished`` event, derived from the node's writes."""
    if node == "planner":
        return f"Planned {len(result.get('plan') or [])} sections"
    if node == "approval_gate":
        return "Plan approved" if result.get("plan_approved") else "Awaiting plan approval"
    if node == "worker":
        drafts = result.get("drafts") or []
        sid = getattr(drafts[0], "section_id", "?") if drafts else "?"
        return f"Drafted section {sid}"
    if node == "reviewer":
        return f"Reviewed {len(result.get('reviews') or [])} section(s)"
    if node == "writer":
        return "Synthesized final report"
    return f"{node} finished"


def chunk_to_events(mode: str, data: Any, cost: CostAccumulator) -> list[BaseModel]:
    """Map one ``(mode, data)`` stream chunk to zero-or-more ``AtlasEvent``s (pure).

    Ordering within a ``tasks`` result: ``status`` → ``review*`` → ``usage*`` →
    ``node_finished`` so a timeline reads coherently. ``usage`` events carry the
    running ``total_cost_usd`` from ``cost``.
    """
    events: list[BaseModel] = []

    if mode == "tasks":
        node = data["name"]
        if not _is_task_result(data):
            events.append(NodeStartedEvent(node=node, section_id=_section_id_from_task(node, data)))
            return events

        result = data.get("result")
        result = result if isinstance(result, dict) else {}
        status = result.get("status")
        if status:
            events.append(StatusEvent(status=status))
        for review in result.get("reviews") or []:
            events.append(ReviewEvent(review=review))
        for usage in result.get("usage_log") or []:
            events.append(
                UsageEventMsg(event=usage, total_cost_usd=cost.add(usage.cost_usd))
            )
        events.append(
            NodeFinishedEvent(
                node=node,
                section_id=_section_id_from_task(node, data),
                summary=_summary(node, result),
            )
        )
        return events

    if mode == "messages":
        msg, meta = data  # (AIMessageChunk, metadata)
        if meta.get("langgraph_node") == "writer":
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                events.append(TokenEvent(node="writer", delta=content))

    return events


def terminal_events(snap: Any) -> list[BaseModel]:
    """After ``astream`` drains: emit ``interrupt`` (paused) or ``done`` (finished).

    Read authoritatively from the graph state snapshot — ``snap.interrupts`` for the
    pending plan (F5 path), else ``final_report_md`` for the completed report.
    """
    if snap.interrupts:
        plan = [SectionPlan(**s) for s in snap.interrupts[0].value["plan"]]
        return [InterruptEvent(payload=InterruptPayload(plan=plan))]
    report = snap.values.get("final_report_md") or ""
    return [DoneEvent(report_md=report)] if report else []
