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
from langchain_core.tracers.context import collect_runs
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
from app.config import settings
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

        The sqlite/postgres savers are **synchronous** and raise ``NotImplementedError``
        on the async checkpointer methods that ``graph.astream`` invokes, so we drive the
        graph with the sync ``graph.stream`` inside an ``asyncio.to_thread`` worker and
        bridge its chunks back to this loop through a queue. The F6 async endpoints still
        never block, and it works for every backend (incl. the ``MemorySaver`` used in
        tests). The saver is opened *inside* the worker thread, so the connection and every
        graph executor thread share one process thread — no cross-thread sqlite access.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        row = self._repo.get(run_id)
        cost = CostAccumulator(seed=row.cost_usd if row else 0.0)
        try:
            # A fresh run (seed state) opens on "planning"; resume continues from the
            # approval interrupt, whose node emits the next status itself.
            if not isinstance(kickoff, Command):
                await emit(StatusEvent(status=kickoff["status"]))

            loop = asyncio.get_running_loop()
            bridge: asyncio.Queue[Any] = asyncio.Queue()
            _DONE = object()

            def _pump() -> None:
                """Run the sync graph in a worker thread, forwarding chunks to the loop.

                ``collect_runs`` is entered *inside* this worker thread — the same thread
                that runs ``graph.stream`` — so the collector's contextvar is active where
                the graph executes (``asyncio.to_thread`` copies the caller context, but
                entering here avoids any ambiguity). Its ``traced_runs[0].id`` is the
                LangSmith root run id, forwarded to the loop for the ``trace_id`` deep-link.
                """
                try:
                    with self._cx() as cp:
                        graph = build_graph(cp)
                        with collect_runs() as run_cb:
                            for chunk in graph.stream(
                                kickoff, config=config, stream_mode=["tasks", "messages"]
                            ):
                                loop.call_soon_threadsafe(
                                    bridge.put_nowait, ("chunk", chunk)
                                )
                        snapshot = graph.get_state(config)
                    # Store the id only when tracing is on, so we never deep-link a trace
                    # that was never exported to LangSmith.
                    trace_id = (
                        str(run_cb.traced_runs[0].id)
                        if settings.LANGSMITH_TRACING and run_cb.traced_runs
                        else None
                    )
                    loop.call_soon_threadsafe(bridge.put_nowait, ("snap", snapshot))
                    loop.call_soon_threadsafe(bridge.put_nowait, ("trace", trace_id))
                except Exception as exc:  # re-raised on the consuming side
                    loop.call_soon_threadsafe(bridge.put_nowait, ("error", exc))
                finally:
                    loop.call_soon_threadsafe(bridge.put_nowait, _DONE)

            pump = asyncio.create_task(asyncio.to_thread(_pump))
            snap = None
            trace_id: str | None = None
            pump_error: Exception | None = None
            while True:
                item = await bridge.get()
                if item is _DONE:
                    break
                kind, data = item
                if kind == "chunk":
                    mode, chunk = data
                    for event in chunk_to_events(mode, chunk, cost):
                        await emit(event)
                elif kind == "snap":
                    snap = data
                elif kind == "trace":
                    trace_id = data
                elif kind == "error":
                    pump_error = data
            await pump
            if pump_error is not None:
                raise pump_error
            assert snap is not None  # set unless an error was raised above

            for event in terminal_events(snap):
                await emit(event)

            values = snap.values
            self._repo.update(
                run_id,
                status=values["status"],
                cost_usd=_total_cost(values),
                report_md=values.get("final_report_md") or None,
                trace_id=trace_id,
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
