"""RunsRepo CRUD + idempotent bootstrap over a temp sqlite file."""

from pathlib import Path

from app.persistence.runs_repo import RunsRepo


def _repo(tmp_path: Path) -> RunsRepo:
    return RunsRepo(db_path=str(tmp_path / "runs.sqlite"))


def test_create_get_round_trip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    row = repo.create("r1", "t1", "Compare vector DBs")

    assert row.status == "planning"
    assert row.cost_usd == 0.0
    assert row.report_md is None

    fetched = repo.get("r1")
    assert fetched is not None
    assert fetched.run_id == "r1"
    assert fetched.thread_id == "t1"
    assert fetched.topic == "Compare vector DBs"
    assert fetched.status == "planning"


def test_update_persists_status_cost_report(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.create("r1", "t1", "topic")

    repo.update("r1", status="awaiting_approval", cost_usd=0.0002)
    mid = repo.get("r1")
    assert mid is not None
    assert mid.status == "awaiting_approval"
    assert mid.cost_usd == 0.0002
    assert mid.report_md is None  # not passed → unchanged

    repo.update("r1", status="done", cost_usd=0.05, report_md="# Report\n")
    done = repo.get("r1")
    assert done is not None
    assert done.status == "done"
    assert done.cost_usd == 0.05
    assert done.report_md == "# Report\n"


def test_list_newest_first(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # created_at is ISO-8601 UTC; distinct topics with monotonically later timestamps.
    repo.create("r1", "t1", "first")
    repo.create("r2", "t2", "second")
    rows = repo.list()
    assert [r.run_id for r in rows] == ["r2", "r1"]


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert _repo(tmp_path).get("nope") is None


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    db = str(tmp_path / "runs.sqlite")
    RunsRepo(db_path=db).create("r1", "t1", "topic")
    # A second repo over the same file must not error and must see the row.
    repo2 = RunsRepo(db_path=db)
    assert repo2.get("r1") is not None
