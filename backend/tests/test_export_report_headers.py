"""GET /api/runs/{id}/report.md — download headers and status codes (F7 §6)."""

from pathlib import Path

import pytest

from tests.api_helpers import build_app, client_for, patch_models, wait_for_status


async def test_download_report_attachment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        run_id = (await client.post("/api/runs", json={"topic": "Compare vector DBs"})).json()[
            "run_id"
        ]

        # Before approval there is no report yet → 409.
        await wait_for_status(client, run_id, "awaiting_approval")
        not_ready = await client.get(f"/api/runs/{run_id}/report.md")
        assert not_ready.status_code == 409

        # Drive to completion, then download.
        await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        await wait_for_status(client, run_id, "done")

        resp = await client.get(f"/api/runs/{run_id}/report.md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert resp.headers["content-disposition"].startswith(
            f'attachment; filename="atlas-report-{run_id}'
        )
        # Body is the run's stored report.
        detail = (await client.get(f"/api/runs/{run_id}")).json()
        assert resp.text == detail["final_report_md"]
        assert resp.text.startswith("# Compare vector DBs")


async def test_download_report_unknown_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        resp = await client.get("/api/runs/does-not-exist/report.md")
        assert resp.status_code == 404
