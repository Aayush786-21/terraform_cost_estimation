"""
Main FastAPI application bootstrap.
Configures middleware and includes routers.
"""
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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
logger.info("GitHub OAuth enabled for client_id=%s", safe_client_id)


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


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    """
    Root endpoint serving simple frontend with Sign in with GitHub button.
    
    Returns:
        HTML page with authentication button
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Terraform Cost Estimation</title>
    </head>
    <body>
        <h1>Terraform Cost Estimation</h1>
        <a href="/auth/login">
            <button>Sign in with GitHub</button>
        </a>
        <br><br>
        <a href="/api/me/repos">
            <button>View My Repos</button>
        </a>
    </body>
    </html>
    """
