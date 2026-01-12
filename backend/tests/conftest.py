"""
Shared pytest fixtures for backend tests.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Set minimal environment variables for testing
os.environ.setdefault('GITHUB_CLIENT_ID', 'test_client_id')
os.environ.setdefault('GITHUB_CLIENT_SECRET', 'test_client_secret')
os.environ.setdefault('SESSION_SECRET', 'test_session_secret_for_testing_only')

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_session():
    """Mock session dictionary."""
    return {
        'github_access_token': 'test_token_123',
        'session_created_at': datetime.utcnow().isoformat(),
        'last_activity_at': datetime.utcnow().isoformat()
    }


@pytest.fixture
def mock_github_client():
    """Mock GitHub client."""
    mock = Mock()
    mock.download_repository_archive = Mock(return_value=b'fake_zip_data')
    return mock


@pytest.fixture
def mock_pricing_client():
    """Mock pricing client."""
    mock = Mock()
    mock.get_price = Mock(return_value=0.10)  # $0.10 per hour
    return mock


@pytest.fixture
def mock_mistral_client():
    """Mock Mistral AI client."""
    mock = Mock()
    mock.chat = Mock(return_value={
        'choices': [{
            'message': {
                'content': '{"resources": []}'
            }
        }]
    })
    return mock


@pytest.fixture
def sample_intent_graph():
    """Sample intent graph for testing."""
    return {
        'providers': ['aws'],
        'resources': [
            {
                'cloud': 'aws',
                'category': 'compute',
                'service': 'EC2',
                'terraform_type': 'aws_instance',
                'name': 'web',
                'region': {'source': 'explicit', 'value': 'us-east-1'},
                'count_model': {'type': 'fixed', 'value': 2}
            }
        ]
    }


@pytest.fixture
def sample_estimate():
    """Sample cost estimate for testing."""
    return {
        'currency': 'USD',
        'total_monthly_cost_usd': 100.0,
        'region': 'us-east-1',
        'pricing_timestamp': datetime.utcnow().isoformat(),
        'coverage': {'aws': 'full'},
        'line_items': [
            {
                'cloud': 'aws',
                'service': 'EC2',
                'resource_name': 'web',
                'terraform_type': 'aws_instance',
                'region': 'us-east-1',
                'monthly_cost_usd': 100.0,
                'pricing_unit': 'hour',
                'category': 'compute',
                'assumptions': ['730 hours/month'],
                'priced': True,
                'confidence': 'high'
            }
        ],
        'unpriced_resources': []
    }


@pytest.fixture
def mock_time(monkeypatch):
    """Mock time for TTL and expiry tests."""
    current_time = datetime.utcnow()
    
    def mock_now():
        return current_time
    
    monkeypatch.setattr('backend.services.snapshot_service.datetime', type('MockDatetime', (), {
        'utcnow': staticmethod(mock_now),
        'fromisoformat': datetime.fromisoformat,
        'timedelta': timedelta
    })())
    
    return current_time
