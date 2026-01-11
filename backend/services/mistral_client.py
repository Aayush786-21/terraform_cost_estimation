"""
Mistral AI API client service.
Handles all interactions with Mistral AI API.
"""
from typing import Dict, Any, List
import httpx
import json

from backend.core.config import config


class MistralAPIError(Exception):
    """Raised when Mistral API request fails."""
    pass


class MistralClient:
    """Service for making Mistral AI API calls."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize Mistral client with API key.
        
        Args:
            api_key: Mistral API key (defaults to config value)
        """
        self.api_key = api_key or config.MISTRAL_API_KEY
        self.base_url = config.MISTRAL_API_BASE_URL
        self.model = config.MISTRAL_MODEL
        self.timeout = config.MISTRAL_TIMEOUT
        self.max_tokens = config.MISTRAL_MAX_TOKENS
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        response_format: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Send chat completion request to Mistral AI API.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0), lower = more deterministic
            response_format: Optional format specification (e.g., {"type": "json_object"})
        
        Returns:
            API response dictionary
        
        Raises:
            MistralAPIError: If API request fails
            httpx.HTTPStatusError: If HTTP request fails
            httpx.TimeoutException: If request times out
        """
        if not self.api_key:
            raise MistralAPIError("Mistral API key is not configured")
        
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPStatusError as error:
            error_detail = "Unknown error"
            try:
                error_response = error.response.json()
                error_detail = error_response.get("error", {}).get("message", str(error))
            except (json.JSONDecodeError, AttributeError):
                error_detail = error.response.text or str(error)
            
            raise MistralAPIError(
                f"Mistral API request failed: {error_detail} (status: {error.response.status_code})"
            ) from error
        
        except httpx.TimeoutException as error:
            raise MistralAPIError(
                f"Mistral API request timed out after {self.timeout}s"
            ) from error
        
        except httpx.RequestError as error:
            raise MistralAPIError(
                f"Failed to connect to Mistral API: {str(error)}"
            ) from error
