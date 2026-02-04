"""FastAPI application entry point."""

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings
from src.database import init_db
from src.services.job_queue import get_job_queue
from src.web.routes import router
from src.web.auth import (
    is_authenticated,
    is_public_path,
    check_password,
    create_auth_cookie,
)

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

    # Log auth status
    if settings.admin_password:
        logger.info("Auth enabled - password protection active")
    else:
        logger.info("Auth disabled - no ADMIN_PASSWORD set")

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


# Auth middleware
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth if no password configured
        if not settings.admin_password:
            return await call_next(request)

        # Allow public paths
        if is_public_path(path):
            return await call_next(request)

        # Check auth
        if not is_authenticated(request):
            logger.debug(f"Auth required for {path}, redirecting to login")
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


app.add_middleware(AuthMiddleware)

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
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "TTS Warehouse API", "docs": "/docs"}


# Login page
@app.get("/login")
async def login_page():
    """Serve the login page."""
    login_path = static_dir / "login.html"
    if login_path.exists():
        return FileResponse(login_path)
    return {"error": "Login page not found"}


@app.post("/login")
async def login(password: str = Form(...)):
    """Handle login."""
    if check_password(password):
        response = RedirectResponse(url="/", status_code=302)
        return create_auth_cookie(response)
    return Response(status_code=401, content="Invalid password")


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=settings.debug,
    )
