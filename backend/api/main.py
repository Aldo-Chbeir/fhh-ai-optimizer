"""FHH AI Optimizer — FastAPI entrypoint.

Run locally:

    uvicorn backend.api.main:app --reload --port 8000

Reads DATABASE_URL from .env (already configured for the TimescaleDB
Docker container on localhost:5433/fhh_optimizers).
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .db import close_pool, init_pool, db_health
from .errors import register_handlers
from .logging_middleware import AccessLogMiddleware, configure_logging
from .routers import (
    admin as admin_router,
    alerts as alerts_router,
    chat as chat_router,
    components as components_router,
    demand as demand_router,
    health as health_router,
    kpis as kpis_router,
    machines as machines_router,
    risk as risk_router,
    sensors as sensors_router,
)


configure_logging("INFO")
log = logging.getLogger("fhh.api")


async def _warm_alert_risk_cache_bg() -> None:
    """Fire-and-forget background warmup. Resolves the per-(machine,
    component) risk for every pair in the fleet so the first /alerts
    request after startup is served from a warm cache instead of paying
    ~7 s of ML inference. Runs concurrently with the server accepting
    requests; if a /alerts call lands before this finishes, it falls
    back to on-demand resolution (slower but correct)."""
    import asyncio, time
    from .db import get_pool
    from .services.alerts import warm_risk_cache
    try:
        # Tiny pause so the server's first request doesn't compete with the
        # warmup on the same connection pool.
        await asyncio.sleep(0.5)
        pool = get_pool()
        async with pool.acquire() as conn:
            t0 = time.perf_counter()
            n = await warm_risk_cache(conn)
            log.info("alerts risk-cache warmup: %d pairs in %.1fs", n, time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001
        log.warning("alerts risk-cache warmup skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    log.info("starting up | api_version=%s", __version__)
    await init_pool()
    health = await db_health()
    if not health.get("connected"):
        log.error(
            "DB connectivity check failed at startup: %s",
            health.get("error", "unknown error"),
        )
    else:
        log.info(
            "DB ok | pg=%s | timescaledb=%s",
            (health.get("version") or "")[:60], health.get("timescaledb_version"),
        )
        if not health.get("timescaledb"):
            log.warning("TimescaleDB extension is NOT active — sensor history endpoints will degrade.")
        # Background pre-warm: serve requests immediately, populate the
        # alert-risk cache in parallel.
        asyncio.create_task(_warm_alert_risk_cache_bg())
    try:
        yield
    finally:
        log.info("shutting down | closing DB pool")
        await close_pool()


app = FastAPI(
    title="FHH AI Optimizer API",
    version=__version__,
    description="Backend for the FHH AI Optimizer dashboard. See API_CONTRACT.md v1.1.",
    lifespan=lifespan,
)


# ---- Middleware --------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js / CRA
        "http://localhost:5173",   # Vite default
        "http://localhost:8080",   # `python -m http.server 8080` (frontend dev)
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
        "null",                    # opening index.html via file:// reports Origin: null
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AccessLogMiddleware)


# ---- Error handlers ----------------------------------------------------------

register_handlers(app)


# ---- Routers -----------------------------------------------------------------

app.include_router(health_router.router)
app.include_router(machines_router.router)
app.include_router(components_router.router)
app.include_router(risk_router.router)
app.include_router(sensors_router.router)
app.include_router(alerts_router.router)
app.include_router(alerts_router.machine_router)
app.include_router(demand_router.router)
app.include_router(chat_router.router)
app.include_router(kpis_router.router)
app.include_router(admin_router.router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "fhh-ai-optimizer-api",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }
