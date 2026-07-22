"""RunService — run lifecycle orchestrator (F5), consumed by the API in F6.

Coordinates the three F5 concerns for one research run:

1. a ``runs`` metadata row (via :class:`~app.persistence.runs_repo.RunsRepo`),
2. the compiled graph (via ``build_graph``), and
3. durable checkpointing (via the injected ``checkpointer_cx``).

``start`` runs the graph until it pauses at the approval interrupt (or finishes);
``resume`` feeds the human's decision back in with ``Command(resume=...)``. Both open
a *fresh* checkpointer + graph per call — no long-lived connection — which is exactly
what makes resume survive a process restart (the checkpoint store is the only shared
state).

The graph and both savers are synchronous, so each call offloads the blocking work to
a worker thread via ``asyncio.to_thread`` — F6's async endpoints never block the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from app.api.sse import (
    CostAccumulator,
    ErrorEvent,
    StatusEvent,
    chunk_to_events,
    terminal_events,
)
from app.graph.builder import build_graph
from app.graph.state import ResearchState
from app.persistence.checkpointer import checkpointer_cx as default_checkpointer_cx
from app.persistence.runs_repo import RunRow, RunsRepo

CheckpointerCx = Callable[[], AbstractContextManager[BaseCheckpointSaver]]

# An async sink for one AtlasEvent — the API supplies one that writes to the run's
# in-memory buffer/subscribers; tests pass a list-appending fake.
Emit = Callable[[BaseModel], Awaitable[None]]


class StartResult(BaseModel):
    """Outcome of :meth:`RunService.start` — enough for F6 to open the SSE stream."""

    run_id: str
    thread_id: str
    status: str
    # The interrupt's ``{"plan": [...]}`` payload when the run paused for approval,
    # else None (e.g. a run that somehow completed without pausing).
    interrupt_plan: list[dict[str, Any]] | None


def _seed_state(topic: str) -> ResearchState:
    """Fresh graph state for a new run (mirrors ``app/graph/demo.py``)."""
    return {
        "topic": topic,
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "tool_calls": [],
        "status": "planning",
    }


def _total_cost(values: dict[str, Any]) -> float:
    """Sum ``cost_usd`` across the run's ``usage_log`` events."""
    return sum(e.cost_usd for e in values.get("usage_log", []))


class RunService:
    """Start and resume research runs, keeping the ``runs`` row in sync with state."""

    def __init__(
        self,
        repo: RunsRepo,
        checkpointer_cx: CheckpointerCx = default_checkpointer_cx,
    ) -> None:
        self._repo = repo
        self._cx = checkpointer_cx

    async def start(self, topic: str) -> StartResult:
        """Create the run row and run the graph until it pauses (or finishes)."""
        run_id = str(uuid4())
        thread_id = str(uuid4())
        self._repo.create(run_id, thread_id, topic)

        status, cost, plan = await asyncio.to_thread(self._invoke_start, topic, thread_id)
        self._repo.update(run_id, status=status, cost_usd=cost)
        return StartResult(
            run_id=run_id, thread_id=thread_id, status=status, interrupt_plan=plan
        )

    async def resume(self, run_id: str, decision: dict[str, Any]) -> RunRow:
        """Feed the human decision back in and drive the run to its next stop."""
        row = self._repo.get(run_id)
        if row is None:
            raise KeyError(f"run {run_id!r} not found")

        status, cost, report_md = await asyncio.to_thread(
            self._invoke_resume, row.thread_id, decision
        )
        self._repo.update(run_id, status=status, cost_usd=cost, report_md=report_md)
        refreshed = self._repo.get(run_id)
        assert refreshed is not None  # just updated it
        return refreshed

    # --- streaming lifecycle (F6) ----------------------------------------------

    async def stream_run(
        self,
        run_id: str,
        thread_id: str,
        kickoff: ResearchState | Command,
        emit: Emit,
    ) -> None:
        """Drive one graph phase to its next stop, emitting AtlasEvents live.

        ``kickoff`` is a seed :class:`ResearchState` (start) or a ``Command(resume=...)``
        (resume). Streams ``tasks``/``messages`` chunks translated to events, then a
        terminal ``interrupt``/``done`` read from the post-stream snapshot, and syncs
        the ``runs`` row. On failure, emits an ``error`` event and marks the row
        ``failed`` before re-raising.

        The checkpointer context stays open for the whole stream; the sync
        ``SqliteSaver`` is safe under async ``astream`` (opened ``check_same_thread=False``
        with an internal lock), so the graph's executor threads may use it freely.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        row = self._repo.get(run_id)
        cost = CostAccumulator(seed=row.cost_usd if row else 0.0)
        try:
            # A fresh run (seed state) opens on "planning"; resume continues from the
            # approval interrupt, whose node emits the next status itself.
            if not isinstance(kickoff, Command):
                await emit(StatusEvent(status=kickoff["status"]))

            with self._cx() as cp:
                graph = build_graph(cp)
                async for mode, data in graph.astream(
                    kickoff, config=config, stream_mode=["tasks", "messages"]
                ):
                    for event in chunk_to_events(mode, data, cost):
                        await emit(event)
                snap = graph.get_state(config)

            for event in terminal_events(snap):
                await emit(event)

            values = snap.values
            self._repo.update(
                run_id,
                status=values["status"],
                cost_usd=_total_cost(values),
                report_md=values.get("final_report_md") or None,
            )
        except Exception as exc:  # graph failure → surface to clients + mark failed
            await emit(ErrorEvent(message=str(exc)))
            self._repo.update(run_id, status="failed")
            raise

    async def get_state_values(self, thread_id: str) -> dict[str, Any]:
        """Snapshot the graph state for a thread (``{}`` if nothing checkpointed yet)."""

        def _snap() -> dict[str, Any]:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            with self._cx() as cp:
                return build_graph(cp).get_state(config).values

        return await asyncio.to_thread(_snap)

    # --- blocking bodies (run inside asyncio.to_thread) ------------------------

    def _invoke_start(
        self, topic: str, thread_id: str
    ) -> tuple[str, float, list[dict[str, Any]] | None]:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        with self._cx() as cp:
            graph = build_graph(cp)
            graph.invoke(_seed_state(topic), config=config)
            snap = graph.get_state(config)
        values = snap.values
        plan = snap.interrupts[0].value["plan"] if snap.interrupts else None
        return values["status"], _total_cost(values), plan

    def _invoke_resume(
        self, thread_id: str, decision: dict[str, Any]
    ) -> tuple[str, float, str | None]:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        with self._cx() as cp:
            graph = build_graph(cp)
            graph.invoke(Command(resume=decision), config=config)
            snap = graph.get_state(config)
        values = snap.values
        return values["status"], _total_cost(values), values.get("final_report_md") or None
