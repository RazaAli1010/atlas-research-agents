"""End-to-end run lifecycle over ASGI (F6 acceptance: endpoints + SSE ordering)."""

from pathlib import Path

import pytest

from tests.api_helpers import build_app, client_for, patch_models, read_events, wait_for_status


def _first_index(events: list[dict], type_: str, **fields: object) -> int:
    for i, e in enumerate(events):
        if e.get("type") == type_ and all(e.get(k) == v for k, v in fields.items()):
            return i
    raise AssertionError(f"no {type_} event {fields} in {[e.get('type') for e in events]}")


async def test_full_lifecycle_streams_ordered_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        created = await client.post("/api/runs", json={"topic": "Compare vector DBs"})
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        assert created.json()["thread_id"]

        # Drive the run start → approval pause → resume → done, then read the full
        # ordered history from the replay buffer in one pass (ASGITransport buffers
        # the response body, so a stream that pauses mid-run can't be tailed live).
        await wait_for_status(client, run_id, "awaiting_approval")
        resumed = await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        assert resumed.status_code == 202
        await wait_for_status(client, run_id, "done")

        full = await read_events(client, run_id, stop_on=("done", "error"))

        # Ordered prefix up to the approval interrupt.
        assert full[0]["type"] == "status" and full[0]["status"] == "planning"
        assert (
            _first_index(full, "status", status="planning")
            < _first_index(full, "node_started", node="planner")
            < _first_index(full, "node_finished", node="planner")
            < _first_index(full, "node_started", node="approval_gate")
            < _first_index(full, "node_finished", node="approval_gate")
            < _first_index(full, "interrupt")
        )
        interrupt = full[_first_index(full, "interrupt")]
        assert len(interrupt["payload"]["plan"]) == 2

        # After the interrupt: worker / review / writer, ending in done with a report.
        assert full[-1]["type"] == "done"
        assert full[-1]["report_md"].strip()
        done_i = len(full) - 1
        worker_i = _first_index(full, "node_started", node="worker")
        assert _first_index(full, "interrupt") < worker_i < done_i
        assert _first_index(full, "review") < done_i
        assert _first_index(full, "node_finished", node="writer") < done_i

        detail = await client.get(f"/api/runs/{run_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "done"
        assert body["final_report_md"].strip()
        assert len(body["usage_log"]) > 0

        listing = await client.get("/api/runs")
        assert listing.status_code == 200
        summary = next(r for r in listing.json() if r["run_id"] == run_id)
        assert summary["status"] == "done"
        assert summary["cost_usd"] > 0
