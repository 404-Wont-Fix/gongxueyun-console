"""Application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.router import api_router
from .db import init_db
from .seed import seed_admin
from .services.scheduler import start_scheduler, stop_scheduler
from .services.holidays import start_calendar_sync, stop_calendar_sync
from .settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_admin()
    if settings.dev_secret:
        logger.warning("APP_SECRET is weak or default: set a random 32+ char secret in production")
    start_calendar_sync()
    start_scheduler()
    yield
    stop_scheduler()
    stop_calendar_sync()


app = FastAPI(
    title="工学云实习助手 · GongXueYun Console",
    version="0.1.0",
    description="Self-hosted attendance assistant. Only confirmed server records are reported as success.",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


# Optional: serve a built frontend from the same container (single-image mode).
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():  # pragma: no cover - only in single-container deployments
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # Never let an unknown API path fall through to the SPA shell.
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        index = _dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "frontend not built"}, status_code=404)
