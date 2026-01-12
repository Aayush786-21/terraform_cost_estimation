"""
Tests for authentication and session management.
"""

import pytest
from datetime import datetime, timedelta
from backend.auth.session_utils import (
    is_session_valid,
    touch_session,
    clear_session
)


def test_session_expires_after_absolute_lifetime():
    """Session expires after 8 hours absolute lifetime."""
    session = {
        'session_created_at': (datetime.utcnow() - timedelta(hours=9)).isoformat(),
        'last_activity_at': (datetime.utcnow() - timedelta(hours=1)).isoformat()
    }
    assert not is_session_valid(session)


def test_session_expires_after_idle_timeout():
    """Session expires after 30 minutes idle timeout."""
    session = {
        'github_access_token': 'test_token',
        'session_created_at': (datetime.utcnow() - timedelta(hours=1)).isoformat(),
        'last_activity_at': (datetime.utcnow() - timedelta(minutes=31)).isoformat()
    }
    assert not is_session_valid(session)


def test_valid_session_extends_idle_timeout():
    """Valid session extends idle timeout on activity."""
    session = {
        'github_access_token': 'test_token',
        'session_created_at': (datetime.utcnow() - timedelta(hours=1)).isoformat(),
        'last_activity_at': (datetime.utcnow() - timedelta(minutes=15)).isoformat()
    }
    assert is_session_valid(session)
    
    # Touch session
    touch_session(session)
    
    # Should still be valid
    assert is_session_valid(session)
    assert 'last_activity_at' in session


def test_logout_clears_session():
    """Logout clears all session data."""
    session = {
        'github_access_token': 'test_token',
        'session_created_at': datetime.utcnow().isoformat(),
        'last_activity_at': datetime.utcnow().isoformat()
    }
    
    clear_session(session)
    
    assert 'github_access_token' not in session
    assert 'session_created_at' not in session
    assert 'last_activity_at' not in session


def test_expired_session_cannot_access_protected_endpoints():
    """Expired session returns 401 on protected endpoints."""
    # This would require mocking session middleware
    # For now, test the session validation logic
    expired_session = {
        'github_access_token': 'test_token',
        'session_created_at': (datetime.utcnow() - timedelta(hours=9)).isoformat(),
        'last_activity_at': (datetime.utcnow() - timedelta(hours=1)).isoformat()
    }
    assert not is_session_valid(expired_session)


def test_session_without_timestamps_is_invalid():
    """Session without timestamps is invalid."""
    session = {}
    assert not is_session_valid(session)


def test_session_within_both_limits_is_valid():
    """Session within both absolute and idle limits is valid."""
    session = {
        'github_access_token': 'test_token',
        'session_created_at': (datetime.utcnow() - timedelta(hours=2)).isoformat(),
        'last_activity_at': (datetime.utcnow() - timedelta(minutes=15)).isoformat()
    }
    assert is_session_valid(session)
