"""Backend-selected checkpointer factory (sqlite/postgres) — F2.

A checkpointer is mandatory for real graph runs (interrupt/resume needs one). The
backend is chosen by ``settings.CHECKPOINT_BACKEND``, never hardcoded (§2.2):
``SqliteSaver`` for local dev, ``PostgresSaver`` for Docker/production.

Both savers' ``from_conn_string`` are context managers whose connection must stay
open for the graph's lifetime, so this factory is itself a context manager — enter
it with ``with checkpointer_cx() as cp:`` and build/run the graph inside.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.config import settings

# Local dev sqlite file (relative to the backend process cwd).
SQLITE_PATH = "atlas_checkpoints.sqlite"


@contextmanager
def checkpointer_cx() -> Iterator[BaseCheckpointSaver]:
    """Yield a set-up checkpointer selected by ``CHECKPOINT_BACKEND``."""
    if settings.CHECKPOINT_BACKEND == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(settings.DATABASE_URL) as cp:
            cp.setup()
            yield cp
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string(SQLITE_PATH) as cp:
            cp.setup()
            yield cp
