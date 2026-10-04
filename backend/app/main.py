"""Application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import admin, auth, geometry, images, projects, scans

log = logging.getLogger("gcg")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    log.info("%s bereit, Daten unter %s", settings.app_name, settings.data_dir)
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(geometry.router)
app.include_router(scans.router)
app.include_router(scans.scoped)
app.include_router(scans.jobs_router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- static frontend --------------------------------------------------------
# Serving the built SPA from the same origin keeps the session cookie simple
# and means one process to run in an LXC container.

_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND / "assets"),
              name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = (_FRONTEND / full_path).resolve()
        if (full_path and candidate.is_file()
                and candidate.is_relative_to(_FRONTEND.resolve())):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend() -> dict:
        return {"detail": "Frontend nicht gebaut. 'npm run build' im Ordner frontend/."}
