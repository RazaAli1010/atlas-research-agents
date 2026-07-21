"""Late-join replay: subscribing after completion yields full history ending in done (F6)."""

from pathlib import Path

import pytest

from tests.api_helpers import build_app, client_for, patch_models, read_events, wait_for_status


async def test_late_join_replays_full_history_ending_in_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        # Run to completion WITHOUT ever subscribing to the event stream.
        run_id = (await client.post("/api/runs", json={"topic": "T"})).json()["run_id"]
        await wait_for_status(client, run_id, "awaiting_approval")
        await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        await wait_for_status(client, run_id, "done")

        # Now a late client connects — it must still get the whole ordered history.
        events = await read_events(client, run_id, stop_on=("done", "error"))
        types = [e["type"] for e in events]

        assert types[0] == "status" and events[0]["status"] == "planning"
        assert "interrupt" in types
        assert "node_finished" in types
        assert types[-1] == "done"
        assert events[-1]["report_md"].strip()
