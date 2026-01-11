"""
Request size limiting middleware for FastAPI.
Protects endpoints from oversized payloads.
"""
from typing import Dict, Set, Optional
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# Size limit constants
MAX_REQUEST_BODY_SIZE = 1_048_576  # 1 MB in bytes
MAX_TERRAFORM_FILE_COUNT = 50
MAX_TERRAFORM_CONTENT_SIZE = 512_000  # 500 KB in bytes
MAX_INTENT_GRAPH_RESOURCES = 200

# Endpoints that require size limiting
PROTECTED_ENDPOINTS: Set[str] = {
    "/api/terraform/files",
    "/api/terraform/interpret",
    "/api/terraform/estimate",
    "/api/terraform/estimate/scenario",
    "/api/terraform/insights",
}


class RequestSizeLimiterMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for request size limiting.
    
    Applies size limits only to configured endpoints.
    Other routes pass through untouched.
    """
    
    async def dispatch(self, request: Request, call_next: ASGIApp):
        """
        Process request and apply size limits if applicable.
        
        Args:
            request: FastAPI request object
            call_next: Next middleware or route handler
        
        Returns:
            Response object
        """
        # Get endpoint path
        path = request.url.path
        
        # Check if this endpoint should be size limited
        if path not in PROTECTED_ENDPOINTS:
            # Pass through for non-protected endpoints
            response = await call_next(request)
            return response
        
        try:
            # Check Content-Length header if present
            content_length = request.headers.get("Content-Length")
            if content_length:
                try:
                    body_size = int(content_length)
                    if body_size > MAX_REQUEST_BODY_SIZE:
                        logger.info(
                            f"Request body size exceeded for {path}: "
                            f"{body_size} bytes (limit: {MAX_REQUEST_BODY_SIZE})"
                        )
                        return JSONResponse(
                            status_code=413,
                            content={
                                "status": "error",
                                "error": "request_too_large",
                                "message": "Request body size exceeds allowed limit of 1 MB.",
                            }
                        )
                except ValueError:
                    # Invalid Content-Length header, continue to body reading
                    pass
            
            # Read request body for validation (up to max size + 1 byte)
            body_bytes = await request.body()
            body_size = len(body_bytes)
            
            # Check raw body size
            if body_size > MAX_REQUEST_BODY_SIZE:
                logger.info(
                    f"Request body size exceeded for {path}: "
                    f"{body_size} bytes (limit: {MAX_REQUEST_BODY_SIZE})"
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "status": "error",
                        "error": "request_too_large",
                        "message": "Request body size exceeds allowed limit of 1 MB.",
                    }
                )
            
            # Parse JSON for payload-aware validation (if body is not empty)
            if body_size > 0:
                try:
                    body_json = json.loads(body_bytes.decode("utf-8"))
                    validation_error = self._validate_payload(path, body_json)
                    
                    if validation_error:
                        logger.info(
                            f"Payload validation failed for {path}: {validation_error}"
                        )
                        return JSONResponse(
                            status_code=413,
                            content={
                                "status": "error",
                                "error": "request_too_large",
                                "message": validation_error,
                            }
                        )
                
                except json.JSONDecodeError:
                    # Invalid JSON - let FastAPI handle this error
                    # We've already validated size, so pass through
                    pass
                except UnicodeDecodeError:
                    # Invalid encoding - let FastAPI handle this
                    # We've already validated size, so pass through
                    pass
                except Exception as error:
                    # Fail closed on unexpected errors
                    logger.error(
                        f"Error during payload validation for {path}: {error}",
                        exc_info=True
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "status": "error",
                            "error": "request_too_large",
                            "message": "Request validation failed.",
                        }
                    )
            
            # Create a new request with the body restored
            # Starlette/FastAPI requires this for body to be readable downstream
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            
            request._receive = receive
            
        except Exception as error:
            # Fail closed on any error
            logger.error(
                f"Error during size limiting for {path}: {error}",
                exc_info=True
            )
            return JSONResponse(
                status_code=413,
                content={
                    "status": "error",
                    "error": "request_too_large",
                    "message": "Request validation failed.",
                }
            )
        
        # Continue to next middleware or route handler
        response = await call_next(request)
        return response
    
    def _validate_payload(self, path: str, body_json: Dict) -> Optional[str]:
        """
        Validate payload-specific constraints based on endpoint.
        
        Args:
            path: Request path
            body_json: Parsed JSON body
        
        Returns:
            Error message if validation fails, None if valid
        """
        # /api/terraform/files - validate file count
        if path == "/api/terraform/files":
            return self._validate_files_request(body_json)
        
        # /api/terraform/interpret - validate file count and total size
        if path == "/api/terraform/interpret":
            return self._validate_interpret_request(body_json)
        
        # /api/terraform/estimate and /api/terraform/estimate/scenario - validate intent graph
        if path in ["/api/terraform/estimate", "/api/terraform/estimate/scenario"]:
            return self._validate_estimate_request(body_json)
        
        # /api/terraform/insights - validate intent graph and estimates
        if path == "/api/terraform/insights":
            return self._validate_insights_request(body_json)
        
        return None
    
    def _validate_files_request(self, body_json: Dict) -> Optional[str]:
        """
        Validate /api/terraform/files request.
        
        Args:
            body_json: Parsed JSON body
        
        Returns:
            Error message if validation fails, None if valid
        """
        # This endpoint doesn't send files in the request body
        # Files are fetched from GitHub
        # So we don't need to validate file count/size here
        return None
    
    def _validate_interpret_request(self, body_json: Dict) -> Optional[str]:
        """
        Validate /api/terraform/interpret request.
        
        Args:
            body_json: Parsed JSON body with 'files' array
        
        Returns:
            Error message if validation fails, None if valid
        """
        files = body_json.get("files", [])
        
        # Check file count
        if len(files) > MAX_TERRAFORM_FILE_COUNT:
            return f"Too many Terraform files: {len(files)} (limit: {MAX_TERRAFORM_FILE_COUNT})"
        
        # Check total content size
        total_size = 0
        for file_data in files:
            if isinstance(file_data, dict):
                content = file_data.get("content", "")
                if isinstance(content, str):
                    total_size += len(content.encode("utf-8"))
        
        if total_size > MAX_TERRAFORM_CONTENT_SIZE:
            return (
                f"Terraform content size exceeds limit: "
                f"{total_size} bytes (limit: {MAX_TERRAFORM_CONTENT_SIZE} bytes)"
            )
        
        return None
    
    def _validate_estimate_request(self, body_json: Dict) -> Optional[str]:
        """
        Validate /api/terraform/estimate request.
        
        Args:
            body_json: Parsed JSON body with 'intent_graph'
        
        Returns:
            Error message if validation fails, None if valid
        """
        intent_graph = body_json.get("intent_graph", {})
        resources = intent_graph.get("resources", [])
        
        if len(resources) > MAX_INTENT_GRAPH_RESOURCES:
            return (
                f"Intent graph too large: {len(resources)} resources "
                f"(limit: {MAX_INTENT_GRAPH_RESOURCES})"
            )
        
        return None
    
    def _validate_insights_request(self, body_json: Dict) -> Optional[str]:
        """
        Validate /api/terraform/insights request.
        
        Args:
            body_json: Parsed JSON body with 'intent_graph' and 'base_estimate'
        
        Returns:
            Error message if validation fails, None if valid
        """
        intent_graph = body_json.get("intent_graph", {})
        resources = intent_graph.get("resources", [])
        
        if len(resources) > MAX_INTENT_GRAPH_RESOURCES:
            return (
                f"Intent graph too large: {len(resources)} resources "
                f"(limit: {MAX_INTENT_GRAPH_RESOURCES})"
            )
        
        # Also validate base_estimate line_items if present
        base_estimate = body_json.get("base_estimate", {})
        line_items = base_estimate.get("line_items", [])
        
        # Intent graph resources is the primary limit, but check line_items too
        # (line_items should be <= resources, so this is defensive)
        if len(line_items) > MAX_INTENT_GRAPH_RESOURCES:
            return (
                f"Cost estimate too large: {len(line_items)} line items "
                f"(limit: {MAX_INTENT_GRAPH_RESOURCES})"
            )
        
        return None
