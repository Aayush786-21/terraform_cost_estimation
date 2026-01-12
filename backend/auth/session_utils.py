"""
Session utilities for authentication and session management.
Handles session validation, expiry, and cleanup.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)


# Session policy constants
ABSOLUTE_SESSION_LIFETIME = timedelta(hours=8)  # 8 hours absolute maximum
IDLE_TIMEOUT = timedelta(minutes=30)  # 30 minutes of inactivity
SESSION_CREATED_AT_KEY = "session_created_at"
LAST_ACTIVITY_AT_KEY = "last_activity_at"
GITHUB_ACCESS_TOKEN_KEY = "github_access_token"


def _parse_ts(ts: str) -> datetime:
    """
    Parse ISO format timestamp string to datetime.
    
    Args:
        ts: ISO format timestamp string
    
    Returns:
        datetime object
    """
    return datetime.fromisoformat(ts)


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
    
    # Check for required timestamp keys
    if SESSION_CREATED_AT_KEY not in session or LAST_ACTIVITY_AT_KEY not in session:
        return False
    
    now = datetime.now(timezone.utc)
    
    try:
        # Parse timestamps
        created_at = _parse_ts(session[SESSION_CREATED_AT_KEY])
        last_activity = _parse_ts(session[LAST_ACTIVITY_AT_KEY])
        
        # Ensure timezone-aware for comparison
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        
        # Check absolute session lifetime
        if now - created_at > ABSOLUTE_SESSION_LIFETIME:
            logger.info("Session expired: absolute lifetime exceeded")
            return False
        
        # Check idle timeout
        if now - last_activity > IDLE_TIMEOUT:
            logger.info("Session expired: idle timeout exceeded")
            return False
        
        return True
    
    except (ValueError, AttributeError, KeyError) as e:
        logger.warning(f"Invalid session timestamp format: {e}")
        return False


def touch_session(session: Dict[str, Any]) -> None:
    """
    Update last_activity_at timestamp to extend idle timeout.
    
    Does NOT extend absolute session lifetime (sliding expiration only for idle timeout).
    
    Args:
        session: Session dictionary from Starlette SessionMiddleware (modified in-place)
    """
    if not session:
        return
    
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
    session[GITHUB_ACCESS_TOKEN_KEY] = access_token
    session[SESSION_CREATED_AT_KEY] = now.isoformat()
    session[LAST_ACTIVITY_AT_KEY] = now.isoformat()
