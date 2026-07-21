"""FastAPI application factory.

Exposes ``GET /api/health`` (F1) plus the run lifecycle + SSE endpoints (F6). The
``RunService`` and event ``RunRegistry`` are constructed once and stashed on
``app.state``; both are injectable so tests can supply a tmp-repo + ``MemorySaver``
service (mirrors ``tests/test_run_service._service``).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_runs import RunRegistry
from app.api.routes_runs import router as runs_router
from app.config import settings
from app.persistence.runs_repo import RunsRepo
from app.services.run_service import RunService


def create_app(
    run_service: RunService | None = None,
    registry: RunRegistry | None = None,
) -> FastAPI:
    app = FastAPI(title="Atlas API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.run_service = run_service or RunService(RunsRepo())
    app.state.registry = registry or RunRegistry()

    app.include_router(runs_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
