"""
Main FastAPI application bootstrap.
Configures middleware and includes routers.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.core.config import config
from backend.auth.github import router as auth_router
from backend.api.repos import router as repos_router
from backend.api.terraform import router as terraform_router


# Validate configuration on startup
try:
    config.validate()
except ValueError as error:
    raise RuntimeError(f"Configuration error: {error}") from error


app = FastAPI(
    title="Terraform Cost Estimation",
    description="GitHub OAuth integration for Terraform cost estimation",
)

# Add session middleware with secure settings
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    max_age=config.SESSION_MAX_AGE,
    same_site="lax",
    https_only=False,  # Set to True in production with HTTPS
)

# Include routers
app.include_router(auth_router)
app.include_router(repos_router)
app.include_router(terraform_router)


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
