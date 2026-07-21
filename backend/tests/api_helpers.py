"""Shared F6 API test helpers (not collected — no ``test_`` prefix).

Builds an app whose graph runs with mocked models (the F5 ``_patch`` pattern), a tmp
``RunsRepo``, and a shared ``MemorySaver`` so start/resume persist across the two
background tasks. Plus a small SSE reader that parses the event stream over
``httpx.ASGITransport``.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.api.routes_runs import RunRegistry
from app.graph.nodes import planner as planner_mod
from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes import worker as worker_mod
from app.graph.nodes.planner import PlannerOutput
from app.graph.state import Review, SectionPlan
from app.main import create_app
from app.persistence.runs_repo import RunsRepo
from app.services.run_service import RunService
from tests.fakes import FakeModel, FakeReviewModel, ai

_APPROVE = Review(section_id="x", verdict="approved", score=0.95, feedback="")


class _PlannerFake:
    """Structured-output fake returning a fixed two-section plan."""

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


def patch_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock every node's model so the graph runs deterministically without network."""
    monkeypatch.setattr(planner_mod, "get_model", lambda _role: _PlannerFake())
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: FakeModel([ai(content="Body.")]))
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: FakeReviewModel([_APPROVE]))


def build_app(tmp_path: Path) -> Any:
    """App wired to a tmp repo + shared MemorySaver service (isolated per test)."""
    repo = RunsRepo(db_path=str(tmp_path / "runs.sqlite"))
    saver = MemorySaver()

    @contextmanager
    def shared_cx() -> Any:
        yield saver

    service = RunService(repo, checkpointer_cx=shared_cx)
    return create_app(run_service=service, registry=RunRegistry())


def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def wait_for_status(
    client: httpx.AsyncClient, run_id: str, status: str, timeout: float = 5.0
) -> None:
    """Poll the *repo-row* status (list endpoint) until it reaches ``status``.

    Uses the list endpoint, not run detail: the row status is what the resume guard
    checks, and it is written by ``stream_run`` only after the background task fully
    settles — so waiting on it avoids the race with the graph-state snapshot.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get("/api/runs")
        row = next((r for r in resp.json() if r["run_id"] == run_id), None)
        if row is not None and row["status"] == status:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {status!r} within {timeout}s")


async def read_events(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    stop_on: tuple[str, ...] = ("done", "error"),
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Consume the SSE stream, returning parsed events up to (incl.) a ``stop_on`` type."""
    events: list[dict[str, Any]] = []
    cur_event: str | None = None

    async def _consume() -> None:
        nonlocal cur_event
        async with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
            async for line in resp.aiter_lines():
                if line.startswith(":") or line.startswith("retry:"):
                    continue
                if line.startswith("event:"):
                    cur_event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    import json

                    data = json.loads(line[len("data:"):].strip())
                    events.append(data)
                    if data.get("type") in stop_on:
                        return

    await asyncio.wait_for(_consume(), timeout=timeout)
    return events
