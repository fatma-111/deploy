"""BugHound application entrypoint.

Serves the JSON API under /api and the dashboard at /. One container, one port,
which is what Railway's free allowance likes best.
"""

from __future__ import annotations

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config.settings import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "web"

@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.knowledge_base import knowledge_base

    kb_stats = knowledge_base.stats()
    logger.info(
        "%s %s started | model=%s | demo_mode=%s | github_token=%s | "
        "orchestrator=%s | knowledge_base_seed_entries=%d",
        settings.app_name,
        settings.version,
        settings.openrouter_model,
        settings.effective_demo_mode,
        bool(settings.github_token),
        settings.orchestrator,
        kb_stats["seed_count"],
    )
    if settings.kb_enabled and kb_stats["seed_count"] == 0:
        logger.warning(
            "Knowledge base is enabled but loaded 0 seed entries. Check that "
            "data/knowledge_base_seed.json shipped in this image (the Dockerfile "
            "must COPY data ./data)."
        )
    yield


app = FastAPI(
    lifespan=lifespan,
    title=f"{settings.app_name} — {settings.app_tagline}",
    version=settings.version,
    description=(
        "Multi-agent bug investigation built on LangGraph. Stateless: no database, "
        "no persisted checkpoints, no stored user code."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health", include_in_schema=False)
def health_alias():
    """Railway health check target."""
    return JSONResponse({"status": "ok", "app": settings.app_name})


if WEB_DIR.exists():
    app.mount(
        "/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets"
    )

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "assets" / "img" / "favicon.svg")
else:  # pragma: no cover - only when the API runs without the bundled UI
    @app.get("/", include_in_schema=False)
    def root():
        return {"app": settings.app_name, "docs": "/api/docs"}
