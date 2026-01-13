"""
Main FastAPI application bootstrap.
Configures middleware and includes routers.
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.core.config import config
from backend.auth.github import router as auth_router
from backend.api.repos import router as repos_router
from backend.api.terraform import router as terraform_router
from backend.api.share import router as share_router
from backend.middleware.rate_limiter import RateLimitMiddleware
from backend.middleware.request_size_limiter import RequestSizeLimiterMiddleware


logger = logging.getLogger(__name__)

# Validate configuration on startup
try:
    config.validate()
except ValueError as error:
    # Fail fast with a clear, non-secret-bearing message
    raise RuntimeError(f"Configuration error: {error}") from error

# Log a safe summary of GitHub OAuth configuration (no secrets)
if config.GITHUB_CLIENT_ID:
    safe_client_id = f"{config.GITHUB_CLIENT_ID[:4]}****"
else:
    safe_client_id = "MISSING"
logger.info(
    "GitHub OAuth enabled for client_id=%s, redirect_uri=%s",
    safe_client_id,
    config.GITHUB_REDIRECT_URI
)


app = FastAPI(
    title="Terraform Cost Estimation",
    description="GitHub OAuth integration for Terraform cost estimation",
)

# Add session middleware with secure settings
# Note: max_age is set to 8 hours (28800 seconds) to match absolute session lifetime
# Actual expiry is enforced in session_utils.py for finer control (idle timeout, etc.)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    max_age=28800,  # 8 hours (matches ABSOLUTE_SESSION_LIFETIME)
    same_site="lax",
    https_only=False,  # Set to True in production with HTTPS
)

# Add rate limiting middleware (after session middleware to access session)
app.add_middleware(RateLimitMiddleware)

# Add request size limiting middleware (after rate limiter)
app.add_middleware(RequestSizeLimiterMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(repos_router)
app.include_router(terraform_router)
app.include_router(share_router)

# NOTE:
# This application is a single-page app (SPA).
# All frontend routing is handled client-side.
# Backend serves index.html at "/" and APIs under "/api/*".

# Mount static files (CSS, JS, etc.)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """
    Root endpoint serving the main single-page frontend.
    
    Returns:
        HTML page (frontend/landing.html or frontend/index.html)
    """
    # Try landing page first, fallback to index.html
    landing_path = frontend_dir / "landing.html"
    index_path = frontend_dir / "index.html"
    
    if landing_path.exists():
        return FileResponse(landing_path)
    elif index_path.exists():
        return FileResponse(index_path)
    else:
        # Fallback if frontend file doesn't exist
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Terraform Cost Estimation</title>
        </head>
        <body>
            <h1>Terraform Cost Estimation</h1>
            <p>Frontend files not found. Please ensure frontend/landing.html or frontend/index.html exists.</p>
        </body>
        </html>
        """)
