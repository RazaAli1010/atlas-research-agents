"""Run-metadata repository — F5.

A deliberately thin, hand-written store for the ``runs`` table (run lifecycle rows
the API in F6 lists and reads). Backend-selected exactly like the checkpointer
(``app/persistence/checkpointer.py``): stdlib ``sqlite3`` on a local file in dev,
``psycopg`` over ``DATABASE_URL`` in Docker/production, chosen by
``settings.CHECKPOINT_BACKEND``.

**Deliberate tradeoff:** schema is created by a ``CREATE TABLE IF NOT EXISTS``
bootstrap on construction rather than Alembic migrations — Alembic is overkill for a
single append-mostly table. Documented in the README.

This module opens a short-lived connection per operation (mirrors the connection
discipline of the checkpointer factory). The table is tiny and access is low-volume,
so per-call connect/close keeps the code simple and thread-safe.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.config import settings

# Local dev sqlite file (sibling of the checkpoints file, relative to backend cwd).
RUNS_SQLITE_PATH = "atlas_runs.sqlite"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    topic      TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cost_usd   REAL NOT NULL DEFAULT 0,
    report_md  TEXT,
    trace_id   TEXT
)
"""

_COLUMNS = (
    "run_id",
    "thread_id",
    "topic",
    "status",
    "created_at",
    "cost_usd",
    "report_md",
    "trace_id",
)


class RunRow(BaseModel):
    """One row of the ``runs`` table (mirrors the API's run summary shape)."""

    run_id: str
    thread_id: str
    topic: str
    status: str
    created_at: str
    cost_usd: float
    report_md: str | None
    trace_id: str | None = None


class RunsRepo:
    """Thin CRUD over the ``runs`` table; bootstraps the schema on construction."""

    def __init__(self, db_path: str | None = None) -> None:
        # sqlite when configured, or whenever an explicit db_path is given (tests).
        self._use_sqlite = db_path is not None or settings.CHECKPOINT_BACKEND == "sqlite"
        self._db_path = db_path or RUNS_SQLITE_PATH
        self._execute(_CREATE_TABLE, commit=True)
        self._ensure_trace_id_column()

    def _ensure_trace_id_column(self) -> None:
        """Add the ``trace_id`` column to a pre-F11 ``runs`` table (idempotent).

        ``CREATE TABLE IF NOT EXISTS`` never alters an already-created table, so a DB
        made before F11 lacks ``trace_id``. sqlite has no ``ADD COLUMN IF NOT EXISTS``,
        so we probe ``PRAGMA table_info``; postgres supports the guarded form directly.
        """
        if self._use_sqlite:
            cols = {r[1] for r in self._execute("PRAGMA table_info(runs)")}
            if "trace_id" not in cols:
                self._execute("ALTER TABLE runs ADD COLUMN trace_id TEXT", commit=True)
        else:
            self._execute(
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS trace_id TEXT", commit=True
            )

    # --- connection / placeholder handling -------------------------------------

    def _connect(self) -> Any:
        """Open a fresh backend-appropriate DB connection."""
        if self._use_sqlite:
            return sqlite3.connect(self._db_path)
        import psycopg  # lazy: only needed on the postgres path (mirrors checkpointer)

        return psycopg.connect(settings.DATABASE_URL)

    def _ph(self) -> str:
        """Positional-parameter placeholder for the active backend."""
        return "?" if self._use_sqlite else "%s"

    def _execute(
        self, sql: str, params: tuple[Any, ...] = (), *, commit: bool = False
    ) -> list[tuple[Any, ...]]:
        """Run one statement, returning fetched rows (empty for writes)."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description is not None else []
            if commit:
                conn.commit()
            return list(rows)
        finally:
            conn.close()

    def _row(self, values: tuple[Any, ...]) -> RunRow:
        return RunRow(**dict(zip(_COLUMNS, values, strict=True)))

    # --- CRUD -------------------------------------------------------------------

    def create(self, run_id: str, thread_id: str, topic: str) -> RunRow:
        """Insert a fresh run row in the initial ``planning`` status."""
        created_at = datetime.now(UTC).isoformat()
        p = self._ph()
        self._execute(
            f"INSERT INTO runs (run_id, thread_id, topic, status, created_at, cost_usd, "
            f"report_md, trace_id) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (run_id, thread_id, topic, "planning", created_at, 0.0, None, None),
            commit=True,
        )
        return RunRow(
            run_id=run_id,
            thread_id=thread_id,
            topic=topic,
            status="planning",
            created_at=created_at,
            cost_usd=0.0,
            report_md=None,
            trace_id=None,
        )

    def update(
        self,
        run_id: str,
        *,
        status: str,
        cost_usd: float | None = None,
        report_md: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Patch ``status`` and, when provided, ``cost_usd`` / ``report_md`` / ``trace_id``.

        ``None`` for ``cost_usd``/``report_md``/``trace_id`` means "leave unchanged", so
        a resume that hasn't produced a report yet never clobbers an existing one, and a
        run streamed with tracing off never nulls a previously-captured ``trace_id``.
        """
        p = self._ph()
        sets = [f"status = {p}"]
        params: list[Any] = [status]
        if cost_usd is not None:
            sets.append(f"cost_usd = {p}")
            params.append(cost_usd)
        if report_md is not None:
            sets.append(f"report_md = {p}")
            params.append(report_md)
        if trace_id is not None:
            sets.append(f"trace_id = {p}")
            params.append(trace_id)
        params.append(run_id)
        self._execute(
            f"UPDATE runs SET {', '.join(sets)} WHERE run_id = {p}",
            tuple(params),
            commit=True,
        )

    def get(self, run_id: str) -> RunRow | None:
        """Fetch one run by id, or ``None`` if absent."""
        p = self._ph()
        rows = self._execute(
            f"SELECT {', '.join(_COLUMNS)} FROM runs WHERE run_id = {p}",
            (run_id,),
        )
        return self._row(rows[0]) if rows else None

    def list(self) -> list[RunRow]:
        """All runs, newest first."""
        rows = self._execute(
            f"SELECT {', '.join(_COLUMNS)} FROM runs ORDER BY created_at DESC"
        )
        return [self._row(r) for r in rows]
