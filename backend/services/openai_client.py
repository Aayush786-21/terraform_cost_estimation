"""
OpenAI API client service.
Handles all interactions with OpenAI API.
"""
from typing import Dict, Any, List
import httpx
import json
import asyncio

from backend.core.config import config
from backend.resilience.circuit_breaker import get_circuit_breaker


class OpenAIAPIError(Exception):
    """Raised when OpenAI API request fails."""
    pass


class OpenAIClient:
    """Service for making OpenAI API calls."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize OpenAI client with API key.
        
        Priority:
        1. Provided api_key parameter (e.g., X-AI-API-Key header)
        2. Server-side config.OPENAI_API_KEY (fallback, dev only)
        
        Args:
            api_key: OpenAI API key (optional, defaults to config value)
        """
        # Use provided key, or fall back to server key
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = config.OPENAI_API_BASE_URL
        self.model = config.OPENAI_MODEL
        # Timeout is configurable via environment (OPENAI_TIMEOUT)
        self.timeout = config.OPENAI_TIMEOUT
        self.max_tokens = config.OPENAI_MAX_TOKENS
        self.retries = 3  # Number of retries for transient errors
        self.backoff_factor = 0.5  # For exponential backoff
        self.circuit_breaker = get_circuit_breaker("openai")
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        response_format: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Send chat completion request to OpenAI API.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0), lower = more deterministic
            response_format: Optional format specification (e.g., {"type": "json_object"})
        
        Returns:
            API response dictionary
        
        Raises:
            OpenAIAPIError: If API request fails
            httpx.HTTPStatusError: If HTTP request fails
            httpx.TimeoutException: If request times out
        """
        if not self.api_key:
            raise OpenAIAPIError("AI API key required. Please provide your own key.")
        
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
        
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            raise OpenAIAPIError(
                "Service temporarily unavailable (circuit breaker open)"
            )
        
        for attempt in range(self.retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    result = response.json()
                    self.circuit_breaker.record_success()
                    return result

            except httpx.HTTPStatusError as error:
                error_detail = "Unknown error"
                try:
                    error_response = error.response.json()
                    error_detail = error_response.get("error", {}).get("message", str(error))
                except (json.JSONDecodeError, AttributeError):
                    error_detail = error.response.text or str(error)
                
                if error.response.status_code in [429, 500, 502, 503, 504] and attempt < self.retries - 1:
                    retry_after = error.response.headers.get("Retry-After")
                    if retry_after:
                        await asyncio.sleep(int(retry_after))
                    else:
                        await asyncio.sleep(self.backoff_factor * (2 ** attempt))
                    continue  # Retry
                # Record failure and raise
                self.circuit_breaker.record_failure()
                raise OpenAIAPIError(
                    f"OpenAI API request failed: {error_detail} (status: {error.response.status_code})"
                ) from error

            except httpx.TimeoutException as error:
                # Record failure for timeout
                self.circuit_breaker.record_failure()
                if attempt < self.retries - 1:
                    await asyncio.sleep(self.backoff_factor * (2 ** attempt))
                    continue  # Retry
                raise OpenAIAPIError(f"OpenAI API request timed out: {str(error)}") from error

            except httpx.RequestError as error:
                # Record failure for network error
                self.circuit_breaker.record_failure()
                if attempt < self.retries - 1:
                    await asyncio.sleep(self.backoff_factor * (2 ** attempt))
                    continue  # Retry
                raise OpenAIAPIError(f"Failed to connect to OpenAI API: {str(error)}") from error
        
        # All retries exhausted
        self.circuit_breaker.record_failure()
        raise OpenAIAPIError("Unknown error after multiple retries with OpenAI API")
