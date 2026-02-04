"""Simple password authentication for the web UI."""

import hashlib
import secrets
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from src.config import get_settings

COOKIE_NAME = "tts_auth"
# Generate a session token on startup (stays valid until server restart)
_session_token: Optional[str] = None


def get_session_token() -> str:
    """Get or create the session token."""
    global _session_token
    if _session_token is None:
        _session_token = secrets.token_hex(32)
    return _session_token


def hash_password(password: str) -> str:
    """Simple hash for comparison."""
    return hashlib.sha256(password.encode()).hexdigest()


def check_password(password: str) -> bool:
    """Check if password matches."""
    settings = get_settings()
    if not settings.admin_password:
        return True  # No password set = always valid
    return password == settings.admin_password


def is_authenticated(request: Request) -> bool:
    """Check if request has valid auth cookie."""
    settings = get_settings()
    if not settings.admin_password:
        return True  # No password set = no auth needed

    cookie = request.cookies.get(COOKIE_NAME)
    return cookie == get_session_token()


def create_auth_cookie(response: Response) -> Response:
    """Add auth cookie to response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=get_session_token(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


def clear_auth_cookie(response: Response) -> Response:
    """Remove auth cookie from response."""
    response.delete_cookie(key=COOKIE_NAME)
    return response


# Public paths that don't require auth
PUBLIC_PATHS = (
    "/feeds/",
    "/audio/",
    "/icons/",
    "/api/health",
    "/login",
    "/static/",
)


def is_public_path(path: str) -> bool:
    """Check if path is public (doesn't need auth)."""
    return any(path.startswith(p) for p in PUBLIC_PATHS)
