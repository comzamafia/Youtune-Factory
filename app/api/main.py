"""FastAPI application — AI YouTube Novel Factory REST API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.routes import jobs, novels, videos
from app.config import settings
from app.core.database import init_db, migrate_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    # ── Startup ──
    logger.info("🚀 Starting AI YouTube Novel Factory…")
    try:
        settings.ensure_dirs()
        logger.info("✅ Directories ensured.")
    except Exception as exc:  # pragma: no cover
        logger.warning("⚠️  Could not create dirs (non-fatal): %s", exc)

    try:
        init_db()
        migrate_db()
        logger.info("✅ Database tables ensured.")
    except Exception as exc:  # pragma: no cover
        # DB may not be ready yet (e.g. Railway cold start without DATABASE_URL).
        # App will still serve /health so Railway health check passes.
        logger.warning("⚠️  DB init failed (app will still start): %s", exc)

    yield

    # ── Shutdown ──
    logger.info("👋 Shutting down.")


app = FastAPI(
    title="AI YouTube Novel Factory",
    description="Automated pipeline: Novel Text → AI Script → AI Voice → AI Image → Video → YouTube",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — configurable via CORS_ORIGINS env var (never wildcard in production)
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(novels.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")


@app.get("/", tags=["frontend"])
def serve_frontend():
    """Serve the frontend dashboard."""
    html = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
    if html.exists():
        return FileResponse(html, media_type="text/html")
    return {"service": "AI YouTube Novel Factory", "status": "running", "version": "1.0.0"}


@app.get("/api/v1/health", tags=["health"])
def health():
    """Detailed health check — does NOT expose credentials."""
    return {
        "status": "healthy",
        "database": "postgresql" if "postgresql" in settings.database_url else "sqlite",
        "redis": "configured",
        "tts_engine": settings.tts_engine,
        "image_engine": settings.image_engine,
        "llm_model": settings.llm_model,
        "gpu_enabled": settings.use_gpu,
    }


@app.get("/api/v1/debug/config", tags=["debug"])
def debug_config():
    """Show non-sensitive runtime config to help debug deployment issues."""
    return {
        "llm_api_base_url": settings.llm_api_base_url,
        "llm_model": settings.llm_model,
        "llm_api_key_set": bool(settings.llm_api_key and settings.llm_api_key != "ollama"),
        "tts_engine": settings.tts_engine,
        "image_engine": settings.image_engine,
        "use_celery": settings.use_celery,
        "use_gpu": settings.use_gpu,
        "database": "postgresql" if "postgresql" in settings.database_url else "sqlite",
    }


@app.get("/api/v1/metrics", tags=["monitoring"])
def metrics_json():
    """Pipeline metrics in JSON format."""
    from app.core.metrics import get_metrics
    return get_metrics()


@app.get("/metrics", tags=["monitoring"])
def metrics_prometheus():
    """Pipeline metrics in Prometheus text exposition format."""
    from app.core.metrics import get_prometheus_text
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=get_prometheus_text(), media_type="text/plain")
