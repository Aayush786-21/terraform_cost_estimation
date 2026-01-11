"""
Configuration module for loading environment variables.
All secrets and configuration values are loaded from .env file.
"""
import os
from typing import Optional


class Config:
    """Application configuration loaded from environment variables."""
    
    # GitHub OAuth Configuration
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_REDIRECT_URI: str = os.getenv(
        "GITHUB_REDIRECT_URI", 
        "http://localhost:8000/auth/callback"
    )
    
    # Session Configuration
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "super-secret-string")
    SESSION_MAX_AGE: int = 3600 * 24 * 7  # 7 days in seconds
    
    # GitHub API URLs
    GITHUB_AUTH_URL: str = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    
    # Mistral AI Configuration
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
    MISTRAL_API_BASE_URL: str = "https://api.mistral.ai/v1"
    MISTRAL_TIMEOUT: int = 120  # 2 minutes for large Terraform files
    MISTRAL_MAX_TOKENS: int = 8192  # Maximum tokens for response
    
    @classmethod
    def validate(cls) -> None:
        """
        Validates that required configuration values are set.
        Raises ValueError if any required configuration is missing.
        """
        if not cls.GITHUB_CLIENT_ID:
            raise ValueError("GITHUB_CLIENT_ID is required")
        if not cls.GITHUB_CLIENT_SECRET:
            raise ValueError("GITHUB_CLIENT_SECRET is required")


config = Config()
