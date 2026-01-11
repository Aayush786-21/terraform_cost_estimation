"""
GitHub OAuth authentication routes.
Handles OAuth flow: login redirect and callback processing.
"""
import secrets
from urllib.parse import urlencode
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
import httpx

from backend.core.config import config
from backend.services.github_client import GitHubClient


router = APIRouter()


def generate_oauth_state() -> str:
    """
    Generate a secure random state string for OAuth flow.
    Used to prevent CSRF attacks.
    
    Returns:
        Random state string
    """
    return secrets.token_urlsafe(32)


@router.get("/auth/login")
async def github_login(request: Request) -> RedirectResponse:
    """
    Initiate GitHub OAuth login flow.
    Generates a secure state token and redirects to GitHub authorization page.
    
    Returns:
        Redirect response to GitHub OAuth authorization page
    """
    state = generate_oauth_state()
    request.session["oauth_state"] = state
    
    params = {
        "client_id": config.GITHUB_CLIENT_ID,
        "redirect_uri": config.GITHUB_REDIRECT_URI,
        "scope": "repo",  # Required for private repo access
        "state": state,
    }
    auth_url = f"{config.GITHUB_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/auth/callback")
async def github_callback(
    request: Request,
    code: str = Query(..., description="OAuth authorization code"),
    state: Optional[str] = Query(None, description="OAuth state parameter"),
) -> RedirectResponse:
    """
    Handle GitHub OAuth callback.
    Validates state parameter, exchanges code for access token,
    and stores token in session.
    
    Args:
        request: FastAPI request object
        code: OAuth authorization code from GitHub
        state: OAuth state parameter from GitHub (must match session state)
    
    Returns:
        Redirect response to home page
    
    Raises:
        HTTPException: If state validation fails or token exchange fails
    """
    # Validate state parameter to prevent CSRF attacks
    session_state = request.session.get("oauth_state")
    if not session_state or session_state != state:
        raise HTTPException(
            status_code=400,
            detail="Invalid or missing OAuth state parameter"
        )
    
    # Clear state from session after validation
    request.session.pop("oauth_state", None)
    
    try:
        # Exchange code for access token
        access_token = await GitHubClient.exchange_code_for_token(code)
        
        # Store token in session (secure, httpOnly cookie via SessionMiddleware)
        request.session["github_access_token"] = access_token
        
        return RedirectResponse(url="/")
    
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=error.response.status_code,
            detail=f"Failed to exchange authorization code: {error.response.text}"
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to GitHub: {str(error)}"
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during authentication: {str(error)}"
        )
