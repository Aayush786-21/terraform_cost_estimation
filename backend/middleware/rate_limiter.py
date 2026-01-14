"""
Rate limiting middleware for FastAPI.
Implements in-memory sliding-window rate limiting.
"""
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# Rate limit configuration: endpoint -> requests per window (per client/IP)
RATE_LIMITS: Dict[str, int] = {
    "/api/terraform/estimate": 50,
    "/api/terraform/estimate/scenario": 50,
    "/api/terraform/estimate/local": 50,
    "/api/terraform/insights": 5,
}

# Time window for rate limiting (seconds)
RATE_LIMIT_WINDOW = 60


class RateLimiter:
    """
    In-memory rate limiter using sliding window approach.
    
    Stores timestamps of recent requests per client and endpoint.
    Cleans up expired timestamps on each request to keep memory bounded.
    """
    
    def __init__(self):
        """Initialize rate limiter with empty storage."""
        # Storage: client_id -> endpoint -> list of request timestamps
        self._storage: Dict[str, Dict[str, List[datetime]]] = defaultdict(lambda: defaultdict(list))
    
    def _get_client_id(self, request: Request) -> str:
        """
        Get client identifier for rate limiting.
        
        Priority:
        1. Session ID (if available)
        2. X-Forwarded-For header (for proxied requests)
        3. Client IP address
        
        Args:
            request: FastAPI request object
        
        Returns:
            Client identifier string
        """
        # Try session ID first
        # SessionMiddleware provides request.session as a dict-like object
        # After SessionMiddleware processes request, session is available
        try:
            if hasattr(request, "session") and request.session:
                # Use a hash of session contents as identifier
                # This provides consistent ID per user session
                session_items = list(request.session.items()) if hasattr(request.session, "items") else []
                session_str = str(sorted(session_items))
                session_hash = hashlib.md5(session_str.encode()).hexdigest()[:8]
                return f"session:{session_hash}"
        except (AttributeError, KeyError, TypeError):
            # Session not available, continue to other methods
            pass
        
        # Try X-Forwarded-For header (for proxied requests)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take first IP in chain
            client_ip = forwarded_for.split(",")[0].strip()
            return f"ip:{client_ip}"
        
        # Fallback to client IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
    
    def _cleanup_expired(self, client_id: str, endpoint: str) -> None:
        """
        Remove expired timestamps for a client and endpoint.
        
        Args:
            client_id: Client identifier
            endpoint: Endpoint path
        """
        if client_id not in self._storage:
            return
        
        if endpoint not in self._storage[client_id]:
            return
        
        cutoff_time = datetime.now() - timedelta(seconds=RATE_LIMIT_WINDOW)
        timestamps = self._storage[client_id][endpoint]
        
        # Remove timestamps older than window
        self._storage[client_id][endpoint] = [
            ts for ts in timestamps if ts > cutoff_time
        ]
        
        # Clean up empty entries
        if not self._storage[client_id][endpoint]:
            del self._storage[client_id][endpoint]
        if not self._storage[client_id]:
            del self._storage[client_id]
    
    def is_allowed(self, client_id: str, endpoint: str, limit: int) -> bool:
        """
        Check if request is allowed under rate limit.
        
        Args:
            client_id: Client identifier
            endpoint: Endpoint path
            limit: Maximum requests per window
        
        Returns:
            True if allowed, False if rate limited
        """
        # Clean up expired timestamps
        self._cleanup_expired(client_id, endpoint)
        
        # Get current timestamps
        timestamps = self._storage[client_id][endpoint]
        current_count = len(timestamps)
        
        # Check if limit exceeded
        if current_count >= limit:
            return False
        
        # Add current request timestamp
        self._storage[client_id][endpoint].append(datetime.now())
        return True
    
    def get_remaining(self, client_id: str, endpoint: str, limit: int) -> int:
        """
        Get remaining requests for a client and endpoint.
        
        Args:
            client_id: Client identifier
            endpoint: Endpoint path
            limit: Maximum requests per window
        
        Returns:
            Number of remaining requests
        """
        self._cleanup_expired(client_id, endpoint)
        timestamps = self._storage[client_id][endpoint]
        current_count = len(timestamps)
        return max(0, limit - current_count)


# Global rate limiter instance
_rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.
    
    Applies rate limits only to configured endpoints.
    Other routes pass through untouched.
    """
    
    async def dispatch(self, request: Request, call_next: ASGIApp):
        """
        Process request and apply rate limiting if applicable.
        
        Args:
            request: FastAPI request object
            call_next: Next middleware or route handler
        
        Returns:
            Response object
        """
        # Get endpoint path
        path = request.url.path
        
        # Check if this endpoint should be rate limited
        if path in RATE_LIMITS:
            limit = RATE_LIMITS[path]
            
            try:
                # Get client identifier
                client_id = _rate_limiter._get_client_id(request)
                
                # Check rate limit
                if not _rate_limiter.is_allowed(client_id, path, limit):
                    # Rate limit exceeded
                    remaining = _rate_limiter.get_remaining(client_id, path, limit)
                    logger.info(
                        f"Rate limit exceeded for endpoint {path} "
                        f"(limit: {limit}/min, remaining: {remaining})"
                    )
                    
                    return JSONResponse(
                        status_code=429,
                        content={
                            "status": "error",
                            "error": "rate_limited",
                            "message": "Too many requests. Please try again later.",
                            "retry_after": RATE_LIMIT_WINDOW,
                        }
                    )
            
            except Exception as error:
                # Fail closed: if rate limiter errors, reject request safely
                logger.error(f"Rate limiter error: {error}", exc_info=True)
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "error",
                        "error": "rate_limit_error",
                        "message": "Rate limiting service unavailable. Please try again later.",
                    }
                )
        
        # Continue to next middleware or route handler
        response = await call_next(request)
        return response
