"""
GitHub OAuth authentication routes.
Handles login, callback, logout, and session management.
"""
import secrets
from urllib.parse import urlencode
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
import httpx

from backend.core.config import config
from backend.services.github_client import GitHubClient
from backend.auth.session_utils import initialize_session, clear_session


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
        
        # Initialize session with access token and timestamps
        initialize_session(request.session, access_token)
        
        return RedirectResponse(url="/")
    
    except httpx.HTTPStatusError as error:
        # Provide clearer error message for redirect_uri mismatches
        error_text = error.response.text or ""
        if "redirect_uri" in error_text.lower() or error.response.status_code == 400:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"OAuth configuration error: The redirect URI '{config.GITHUB_REDIRECT_URI}' "
                    "is not registered in your GitHub OAuth app. "
                    "Please add this exact URL to your GitHub OAuth app's authorized redirect URIs."
                )
            )
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


@router.post("/auth/logout")
async def logout(request: Request) -> Dict[str, Any]:
    """
    Logout endpoint.
    
    Clears session data and invalidates authentication.
    
    Returns:
        JSON response confirming logout
    """
    clear_session(request.session)
    return {
        "status": "ok",
        "message": "Logged out successfully"
    }
