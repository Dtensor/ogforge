"""ogforge — Dynamic Open-Graph / social-card image API (SaaS).

Boots a FastAPI app that serves a marketing/dashboard frontend (routes_web) and a
key-authenticated image API (routes_api). Monetization (Stripe subscription + webhook
reconciliation) lives in billing.py and is wired through routes_web.
"""
from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

import logging

from .config import settings
from .db import _database_url, _get_pool, _is_pg, init_db
from . import routes_api, routes_web

log = logging.getLogger("ogforge")

def create_app() -> FastAPI:
    """Application factory. Used by uvicorn (module-level `app`) and by tests."""
    app = FastAPI(title="ogforge", description="Dynamic OG image API", version="1.0.0")
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    app.include_router(routes_web.router)
    app.include_router(routes_api.router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        # Warm the Postgres pool now (lifespan context), so request handlers borrow
        # already-open connections instead of calling psycopg.connect() inside the
        # threadpool while the event loop runs (which intermittently blocks).
        if _is_pg(_database_url()):
            pool = _get_pool()
            pool.wait(timeout=20)
            log.warning("pg pool ready: %s", pool.get_stats())

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "stripe_enabled": settings.stripe_enabled}

    return app


app = create_app()
