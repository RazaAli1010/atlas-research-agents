"""Resume endpoint guards: status/existence checks + edit-payload validation (F6)."""

from pathlib import Path

import pytest

from tests.api_helpers import build_app, client_for, patch_models, read_events, wait_for_status


async def test_double_resume_and_unknown_run_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        # Unknown run → 404.
        unknown = await client.post("/api/runs/nope/resume", json={"action": "approve"})
        assert unknown.status_code == 404

        run_id = (await client.post("/api/runs", json={"topic": "T"})).json()["run_id"]
        await wait_for_status(client, run_id, "awaiting_approval")

        # First resume succeeds; drive to done.
        first = await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        assert first.status_code == 202
        await read_events(client, run_id, stop_on=("done", "error"))
        await wait_for_status(client, run_id, "done")

        # Second resume on a finished run → 409 (not awaiting approval).
        second = await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        assert second.status_code == 409


async def test_edit_payload_validation_and_clamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        run_id = (await client.post("/api/runs", json={"topic": "T"})).json()["run_id"]
        await wait_for_status(client, run_id, "awaiting_approval")

        # edit with no plan → 422.
        no_plan = await client.post(f"/api/runs/{run_id}/resume", json={"action": "edit"})
        assert no_plan.status_code == 422

        # edit with > MAX_SECTIONS sections → accepted, clamped to 6 downstream.
        big_plan = [
            {"id": f"s{i}", "title": f"T{i}", "objective": "O", "suggested_queries": ["q"]}
            for i in range(1, 9)
        ]
        resumed = await client.post(
            f"/api/runs/{run_id}/resume", json={"action": "edit", "plan": big_plan}
        )
        assert resumed.status_code == 202

        await read_events(client, run_id, stop_on=("done", "error"))
        await wait_for_status(client, run_id, "done")

        detail = (await client.get(f"/api/runs/{run_id}")).json()
        assert len(detail["plan"]) <= 6
