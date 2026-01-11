"""
Session utilities for authentication and session management.
Handles session validation, expiry, and cleanup.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


# Session policy constants
ABSOLUTE_SESSION_LIFETIME = timedelta(hours=8)  # 8 hours absolute maximum
IDLE_TIMEOUT = timedelta(minutes=30)  # 30 minutes of inactivity
SESSION_CREATED_AT_KEY = "session_created_at"
LAST_ACTIVITY_AT_KEY = "last_activity_at"
GITHUB_ACCESS_TOKEN_KEY = "github_access_token"


def is_session_valid(session: Dict[str, Any]) -> bool:
    """
    Check if session is valid based on expiry rules.
    
    Validates:
    - Session exists and has required keys
    - Absolute lifetime (8 hours) not exceeded
    - Idle timeout (30 minutes) not exceeded
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware
    
    Returns:
        True if session is valid, False otherwise
    """
    if not session:
        return False
    
    # Check for required keys
    if GITHUB_ACCESS_TOKEN_KEY not in session:
        return False
    
    now = datetime.now()
    
    # Check absolute session lifetime
    session_created_at = session.get(SESSION_CREATED_AT_KEY)
    if session_created_at:
        if isinstance(session_created_at, str):
            # Parse ISO format string
            try:
                session_created_at = datetime.fromisoformat(session_created_at)
            except (ValueError, AttributeError):
                logger.warning("Invalid session_created_at format, treating as expired")
                return False
        
        if isinstance(session_created_at, datetime):
            elapsed = now - session_created_at
            if elapsed > ABSOLUTE_SESSION_LIFETIME:
                logger.info("Session expired: absolute lifetime exceeded")
                return False
    
    # Check idle timeout
    last_activity_at = session.get(LAST_ACTIVITY_AT_KEY)
    if last_activity_at:
        if isinstance(last_activity_at, str):
            # Parse ISO format string
            try:
                last_activity_at = datetime.fromisoformat(last_activity_at)
            except (ValueError, AttributeError):
                logger.warning("Invalid last_activity_at format, treating as expired")
                return False
        
        if isinstance(last_activity_at, datetime):
            idle_time = now - last_activity_at
            if idle_time > IDLE_TIMEOUT:
                logger.info("Session expired: idle timeout exceeded")
                return False
    
    return True


def touch_session(session: Dict[str, Any]) -> None:
    """
    Update last_activity_at timestamp to extend idle timeout.
    
    Does NOT extend absolute session lifetime (sliding expiration only for idle timeout).
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware (modified in-place)
    """
    if not session:
        return
    
    now = datetime.now()
    session[LAST_ACTIVITY_AT_KEY] = now.isoformat()
    
    # Ensure session_created_at exists (for new sessions)
    if SESSION_CREATED_AT_KEY not in session:
        session[SESSION_CREATED_AT_KEY] = now.isoformat()


def clear_session(session: Dict[str, Any]) -> None:
    """
    Clear all session data.
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware (modified in-place)
    """
    if not session:
        return
    
    session.clear()
    logger.info("Session cleared")


def get_access_token_from_session(session: Dict[str, Any]) -> Optional[str]:
    """
    Get GitHub access token from session if valid.
    
    Validates session and touches it if valid.
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware
    
    Returns:
        GitHub access token if session is valid, None otherwise
    """
    if not is_session_valid(session):
        return None
    
    # Touch session to extend idle timeout (sliding expiration)
    touch_session(session)
    
    return session.get(GITHUB_ACCESS_TOKEN_KEY)


def initialize_session(session: Dict[str, Any], access_token: str) -> None:
    """
    Initialize session with access token and timestamps.
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware (modified in-place)
        access_token: GitHub OAuth access token
    """
    now = datetime.now()
    session[GITHUB_ACCESS_TOKEN_KEY] = access_token
    session[SESSION_CREATED_AT_KEY] = now.isoformat()
    session[LAST_ACTIVITY_AT_KEY] = now.isoformat()
