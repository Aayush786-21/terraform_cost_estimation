"""
API routes for repository operations.
"""
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
import httpx

from backend.services.github_client import GitHubClient


router = APIRouter()


def get_access_token_from_session(request: Request) -> str:
    """
    Extract GitHub access token from session.
    
    Args:
        request: FastAPI request object
    
    Returns:
        GitHub access token string
    
    Raises:
        HTTPException: If user is not authenticated
    """
    token = request.session.get("github_access_token")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please sign in with GitHub."
        )
    return token


@router.get("/api/me/repos")
async def get_user_repositories(request: Request) -> Dict[str, Any]:
    """
    Fetch user's GitHub repositories (including private).
    
    Requires authentication via GitHub OAuth.
    
    Returns:
        JSON response with list of repositories
    
    Raises:
        HTTPException: If authentication fails or GitHub API call fails
    """
    try:
        access_token = get_access_token_from_session(request)
        github_client = GitHubClient(access_token)
        repositories = await github_client.get_user_repositories()
        
        return {
            "repos": repositories,
            "count": len(repositories)
        }
    
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=error.response.status_code,
            detail=f"GitHub API error: {error.response.text}"
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to GitHub API: {str(error)}"
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(error)}"
        )
