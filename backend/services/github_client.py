"""
GitHub API client service.
Handles all interactions with GitHub's API.
"""
from typing import List, Dict, Any
import httpx

from backend.core.config import config


class GitHubClient:
    """Service for making GitHub API calls."""
    
    def __init__(self, access_token: str):
        """
        Initialize GitHub client with access token.
        
        Args:
            access_token: GitHub OAuth access token
        """
        self.access_token = access_token
        self.base_url = config.GITHUB_API_BASE_URL
        self.headers = {
            "Authorization": f"token {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
    
    async def get_user_repositories(
        self, 
        per_page: int = 100, 
        visibility: str = "all"
    ) -> List[Dict[str, Any]]:
        """
        Fetch user's repositories from GitHub API.
        
        Args:
            per_page: Number of repositories per page
            visibility: Repository visibility filter (all, public, private)
        
        Returns:
            List of repository dictionaries
        
        Raises:
            httpx.HTTPStatusError: If GitHub API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/user/repos",
                headers=self.headers,
                params={
                    "per_page": per_page,
                    "visibility": visibility,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    
    async def download_repository_archive(
        self, 
        owner: str, 
        repo: str, 
        ref: str = "main"
    ) -> bytes:
        """
        Download repository archive (zipball) for the given branch/ref.
        Uses GitHub API archive endpoint: GET /repos/{owner}/{repo}/zipball/{ref}
        
        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            ref: Branch, tag, or commit SHA (default: "main")
        
        Returns:
            Raw bytes of the ZIP archive
        
        Raises:
            httpx.HTTPStatusError: If GitHub API request fails (404 if repo/branch not found)
        """
        async with httpx.AsyncClient() as client:
            archive_url = f"{self.base_url}/repos/{owner}/{repo}/zipball/{ref}"
            response = await client.get(
                archive_url,
                headers=self.headers,
                timeout=60.0,  # Longer timeout for archive downloads
            )
            response.raise_for_status()
            return response.content
    
    @classmethod
    async def exchange_code_for_token(cls, code: str) -> str:
        """
        Exchange OAuth authorization code for access token.
        Class method since token is not yet available.
        
        Args:
            code: OAuth authorization code from GitHub callback
        
        Returns:
            Access token string
        
        Raises:
            httpx.HTTPStatusError: If token exchange fails
            ValueError: If access token is not present in response
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.GITHUB_TOKEN_URL,
                data={
                    "client_id": config.GITHUB_CLIENT_ID,
                    "client_secret": config.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": config.GITHUB_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise ValueError("Access token not found in GitHub response")
            
            return access_token
