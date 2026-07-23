"""Run lifecycle endpoints + SSE streaming (SHARED CONTEXT §7) — F6.

``POST /api/runs`` returns immediately; the graph runs as a per-run background asyncio
task that streams typed ``AtlasEvent``s into an in-memory :class:`RunStream` (append-only
history for replay + live subscriber queues). ``GET /api/runs/{id}/events`` replays the
buffered history then live-tails, so a client joining mid-run or after completion always
sees the full ordered stream ending in ``done``.

**Honest scaling limit:** the registry is in-process, unbounded, and single-worker — a
real deployment would push events through a broker (Redis pub/sub, etc.) and run the
graph on a task queue. Documented in the README.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from langgraph.types import Command
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.sse import to_sse
from app.graph.state import (
    MAX_SECTIONS,
    Review,
    SectionDraft,
    SectionPlan,
    UsageEvent,
)
from app.persistence.runs_repo import RunRow
from app.services.run_service import RunService, _seed_state

router = APIRouter(prefix="/api")

_TERMINAL_EVENTS = ("done", "error")


# --- in-memory event fan-out --------------------------------------------------


@dataclass
class RunStream:
    """One run's append-only event history plus its live subscriber queues."""

    buffer: list[dict[str, str]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, str]]] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    finished: bool = False

    async def emit(self, ev: BaseModel) -> None:
        """Append an event to history and fan it out to all subscribers (atomic)."""
        payload = to_sse(ev)
        async with self.lock:
            self.buffer.append(payload)
            if payload["event"] in _TERMINAL_EVENTS:
                self.finished = True
            for q in self.subscribers:
                q.put_nowait(payload)

    async def subscribe(self) -> tuple[list[dict[str, str]], asyncio.Queue[dict[str, str]]]:
        """Register a subscriber and snapshot history under one lock (exactly-once)."""
        async with self.lock:
            q: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            self.subscribers.add(q)
            return list(self.buffer), q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, str]]) -> None:
        async with self.lock:
            self.subscribers.discard(q)


class RunRegistry:
    """Per-``run_id`` :class:`RunStream` records (retained for the process lifetime)."""

    def __init__(self) -> None:
        self._runs: dict[str, RunStream] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(self, run_id: str) -> RunStream:
        stream = RunStream()
        self._runs[run_id] = stream
        return stream

    def get(self, run_id: str) -> RunStream | None:
        return self._runs.get(run_id)

    def spawn(self, run_id: str, coro: Any) -> None:
        """Run ``coro`` as a tracked background task (held so it isn't GC'd)."""
        task = asyncio.create_task(coro)
        self._tasks[run_id] = task

        def _cleanup(t: asyncio.Task[None]) -> None:
            self._tasks.pop(run_id, None)
            if not t.cancelled():
                t.exception()  # retrieve to suppress "never retrieved" warnings

        task.add_done_callback(_cleanup)


# --- request / response models ------------------------------------------------


class CreateRunRequest(BaseModel):
    topic: str = Field(min_length=1)


class CreateRunResponse(BaseModel):
    run_id: str
    thread_id: str


class RunSummary(BaseModel):
    run_id: str
    topic: str
    status: str
    created_at: str
    cost_usd: float


class ResumeRequest(BaseModel):
    action: str  # "approve" | "edit" — cross-field checked in the handler
    plan: list[SectionPlan] | None = None


class RunDetail(BaseModel):
    run_id: str
    thread_id: str
    topic: str
    status: str
    created_at: str
    cost_usd: float
    plan: list[SectionPlan]
    plan_approved: bool
    drafts: list[SectionDraft]
    reviews: list[Review]
    revision_counts: dict[str, int]
    final_report_md: str
    usage_log: list[UsageEvent]
    cost_breakdown: dict[str, float]  # node -> summed cost_usd (derived from usage_log)
    trace_id: str | None = None  # LangSmith root run id for the deep-link (F11); null when untraced

    @classmethod
    def from_row_and_state(cls, row: RunRow, values: dict[str, Any]) -> RunDetail:
        breakdown: dict[str, float] = {}
        for ev in values.get("usage_log") or []:
            breakdown[ev.node] = breakdown.get(ev.node, 0.0) + ev.cost_usd
        return cls(
            run_id=row.run_id,
            thread_id=row.thread_id,
            topic=row.topic,
            status=values.get("status") or row.status,
            created_at=row.created_at,
            cost_usd=row.cost_usd,
            plan=values.get("plan") or [],
            plan_approved=values.get("plan_approved") or False,
            drafts=values.get("drafts") or [],
            reviews=values.get("reviews") or [],
            revision_counts=values.get("revision_counts") or {},
            final_report_md=values.get("final_report_md") or "",
            usage_log=values.get("usage_log") or [],
            cost_breakdown=breakdown,
            trace_id=row.trace_id,
        )


# --- dependencies -------------------------------------------------------------


def _service(request: Request) -> RunService:
    service: RunService = request.app.state.run_service
    return service


def _registry(request: Request) -> RunRegistry:
    registry: RunRegistry = request.app.state.registry
    return registry


# --- endpoints ----------------------------------------------------------------


@router.post("/runs", status_code=201)
async def create_run(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    """Create a run and kick off graph execution in the background; return ids at once."""
    svc = _service(request)
    registry = _registry(request)

    run_id = str(uuid4())
    thread_id = str(uuid4())
    svc._repo.create(run_id, thread_id, body.topic)
    stream = registry.create(run_id)
    registry.spawn(
        run_id,
        svc.stream_run(run_id, thread_id, _seed_state(body.topic), stream.emit),
    )
    return CreateRunResponse(run_id=run_id, thread_id=thread_id)


@router.get("/runs")
async def list_runs(request: Request) -> list[RunSummary]:
    """All runs, newest first (summary shape)."""
    rows = _service(request)._repo.list()
    return [
        RunSummary(
            run_id=r.run_id,
            topic=r.topic,
            status=r.status,
            created_at=r.created_at,
            cost_usd=r.cost_usd,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> RunDetail:
    """Full state snapshot for one run."""
    svc = _service(request)
    row = svc._repo.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    values = await svc.get_state_values(row.thread_id)
    return RunDetail.from_row_and_state(row, values)


@router.get("/runs/{run_id}/report.md")
async def download_report(run_id: str, request: Request) -> Response:
    """Download the final report as a Markdown attachment (SHARED CONTEXT §7).

    Serves the persisted ``runs.report_md``; falls back to the live graph-state
    snapshot for a run whose row hasn't been synced yet. ``409`` while no report
    exists (run still in progress / awaiting approval).
    """
    svc = _service(request)
    row = svc._repo.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")

    report = row.report_md
    if not report:  # not yet synced to the row — read the authoritative state
        values = await svc.get_state_values(row.thread_id)
        report = values.get("final_report_md") or ""
    if not report:
        raise HTTPException(status_code=409, detail="report not ready")

    return Response(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="atlas-report-{run_id}.md"'
        },
    )


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, body: ResumeRequest, request: Request) -> Response:
    """Resume an interrupted run with the human's approve/edit decision."""
    svc = _service(request)
    registry = _registry(request)

    if body.action not in ("approve", "edit"):
        raise HTTPException(status_code=422, detail="action must be 'approve' or 'edit'")

    row = svc._repo.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if row.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail="run is not awaiting approval")

    if body.action == "edit":
        if not body.plan:
            raise HTTPException(status_code=422, detail="edit requires a non-empty plan")
        clamped = body.plan[:MAX_SECTIONS]
        decision: dict[str, Any] = {
            "action": "edit",
            "plan": [p.model_dump() for p in clamped],
        }
    else:
        decision = {"action": "approve"}

    stream = registry.get(run_id)
    if stream is None:  # process restarted since start — rebuild a fresh stream
        stream = registry.create(run_id)
    registry.spawn(
        run_id,
        svc.stream_run(run_id, row.thread_id, Command(resume=decision), stream.emit),
    )
    return Response(status_code=202)


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> EventSourceResponse:
    """SSE stream: replay buffered history, then live-tail until ``done``/``error``."""
    stream = _registry(request).get(run_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator() -> Any:
        history, queue = await stream.subscribe()
        try:
            for payload in history:
                yield payload
                if payload["event"] in _TERMINAL_EVENTS:
                    return
            while True:
                payload = await queue.get()
                yield payload
                if payload["event"] in _TERMINAL_EVENTS:
                    return
        finally:
            await stream.unsubscribe(queue)

    return EventSourceResponse(event_generator())
