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
    ).rstrip("/")  # Normalize: remove trailing slash for exact GitHub match
    
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
    
    # Pricing Configuration
    AWS_PRICING_REGION: str = os.getenv("AWS_PRICING_REGION", "us-east-1")
    PRICING_CACHE_TTL_SECONDS: int = int(os.getenv("PRICING_CACHE_TTL_SECONDS", "86400"))  # 24 hours
    HOURS_PER_MONTH: int = 730  # Standard assumption: 24/7 operation
    
    @classmethod
    def validate(cls) -> None:
        """
        Validates that required configuration values are set.
        
        Raises:
            ValueError: If any required configuration is missing or invalid.
        """
        if not cls.GITHUB_CLIENT_ID:
            raise ValueError("GITHUB_CLIENT_ID is required")
        if not cls.GITHUB_CLIENT_SECRET:
            raise ValueError("GITHUB_CLIENT_SECRET is required")
        
        # Validate redirect_uri format
        if not cls.GITHUB_REDIRECT_URI:
            raise ValueError("GITHUB_REDIRECT_URI is required")
        if not cls.GITHUB_REDIRECT_URI.startswith(("http://", "https://")):
            raise ValueError(
                f"GITHUB_REDIRECT_URI must be a valid URL (got: {cls.GITHUB_REDIRECT_URI})"
            )
        
        # Mistral model is required so that AI calls are well-defined.
        # API key is optional because users can provide their own via X-AI-API-Key.
        if not cls.MISTRAL_MODEL:
            raise ValueError("MISTRAL_MODEL is required")


config = Config()
