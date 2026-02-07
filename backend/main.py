"""FastAPI entry point for Ctrl+Apply backend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db import close as close_db
from backend.db import get_connection
from backend.routers import form, profile, ws
from backend.services.llm_service import llm_service
from backend.services.playwright_service import playwright_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Ctrl+Apply backend on %s:%d", settings.host, settings.port)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cover_letters_dir.mkdir(parents=True, exist_ok=True)

    # Initialize DuckDB
    get_connection()

    # Initialize LLM service
    await llm_service.initialize()

    # Try to connect Playwright (non-fatal if Chrome isn't running yet)
    try:
        await playwright_service.connect()
    except Exception as e:
        logger.warning("CDP connection failed at startup (will retry on demand): %s", e)

    yield

    # Shutdown
    await playwright_service.disconnect()
    close_db()
    logger.info("Ctrl+Apply backend stopped")


app = FastAPI(
    title="Ctrl+Apply",
    description="Job application automation backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost only; tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(ws.router)
app.include_router(profile.router)
app.include_router(form.router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "playwright_connected": playwright_service.is_connected,
        "llm_mode": settings.llm_mode,
    }


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
