"""FastAPI application entry point."""

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv()

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.database import init_db
from src.services.job_queue import get_job_queue
from src.web.routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting TTS Warehouse...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start background job processor
    job_queue = get_job_queue()
    job_queue.start_background_processor(interval_seconds=2.0)
    logger.info("Background job processor started")

    yield

    # Shutdown
    logger.info("Shutting down TTS Warehouse...")
    job_queue.stop_background_processor()
    logger.info("Background job processor stopped")


# Create FastAPI app
app = FastAPI(
    title="TTS Warehouse",
    description="Self-hosted TTS feed generator for articles, RSS feeds, and Royal Road books",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Serve static files (frontend)
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Serve index.html at root
@app.get("/")
async def root():
    """Serve the dashboard."""
    from fastapi.responses import FileResponse

    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "TTS Warehouse API", "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=settings.debug,
    )
