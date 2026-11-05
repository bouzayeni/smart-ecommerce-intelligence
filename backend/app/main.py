"""FastAPI application factory.

Run (from the repo root):
    uv run --all-groups uvicorn app.main:app --app-dir backend --reload
Docs: http://localhost:8000/docs
"""

import sqlalchemy as sa
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import analytics, auth
from app.core.config import get_settings
from app.core.errors import ApiError, register_error_handlers
from app.core.observability import RequestContextMiddleware, configure_logging
from app.core.rate_limit import limiter
from app.db.session import app_engine, read_engine

health = APIRouter(tags=["health"])


@health.get("/health")
def liveness():
    return {"status": "ok"}


@health.get("/health/ready")
def readiness():
    """Both database roles reachable (used by container health checks)."""
    try:
        for engine in (read_engine(), app_engine()):
            with engine.connect() as conn:
                conn.execute(sa.text("select 1"))
    except Exception as exc:
        raise ApiError(503, "not_ready", "Database unavailable") from exc
    return {"status": "ready"}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Analytics, ML scores, forecasts and recommendations over the Olist "
        "warehouse (historical 2016-2018 data). All responses are read from the "
        "warehouse; nothing is generated.",
    )
    app.state.limiter = limiter
    register_error_handlers(app)
    # Order: the last added middleware runs first.
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(analytics.router)
    api.include_router(health)
    app.include_router(api)
    return app


app = create_app()
