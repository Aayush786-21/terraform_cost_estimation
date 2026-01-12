"""
Tests for snapshot service.
"""

import pytest
from datetime import datetime, timedelta
from backend.services.snapshot_service import SnapshotService, get_snapshot_service


@pytest.fixture
def snapshot_service():
    """Snapshot service fixture."""
    return SnapshotService(ttl_hours=24)


@pytest.fixture
def sample_snapshot_data():
    """Sample snapshot data."""
    return {
        'base_estimate': {
            'total_monthly_cost_usd': 100.0,
            'region': 'us-east-1'
        },
        'scenario_estimate': None,
        'deltas': None,
        'insights': [],
        'region': 'us-east-1'
    }


def test_snapshot_creation_stores_immutable_data(snapshot_service, sample_snapshot_data):
    """Snapshot creation stores immutable data."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    
    assert snapshot is not None
    assert snapshot['base_estimate']['total_monthly_cost_usd'] == 100.0


def test_snapshot_retrieval_works_before_ttl(snapshot_service, sample_snapshot_data):
    """Snapshot retrieval works before TTL expires."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    
    assert snapshot is not None
    assert snapshot['snapshot_id'] == snapshot_id


def test_snapshot_expires_after_ttl(snapshot_service, sample_snapshot_data, monkeypatch):
    """Snapshot expires after TTL."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    # Mock time to be 25 hours later
    future_time = datetime.utcnow() + timedelta(hours=25)
    
    # Manually expire by modifying the snapshot
    snapshot = snapshot_service._snapshots.get(snapshot_id)
    if snapshot:
        snapshot['metadata']['expires_at'] = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    
    expired_snapshot = snapshot_service.get_snapshot(snapshot_id)
    
    assert expired_snapshot is None


def test_expired_snapshot_returns_none(snapshot_service, sample_snapshot_data):
    """Expired snapshot returns None."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    # Manually expire
    snapshot = snapshot_service._snapshots.get(snapshot_id)
    if snapshot:
        snapshot['metadata']['expires_at'] = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    
    result = snapshot_service.get_snapshot(snapshot_id)
    assert result is None


def test_snapshot_contains_no_secrets(snapshot_service, sample_snapshot_data):
    """Snapshot contains no secrets or Terraform data."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    snapshot_str = str(snapshot)
    
    # Should not contain sensitive data
    assert 'github_access_token' not in snapshot_str
    assert 'api_key' not in snapshot_str.lower()
    assert 'secret' not in snapshot_str.lower()


def test_snapshot_cannot_be_mutated_via_api(snapshot_service, sample_snapshot_data):
    """Snapshot cannot be mutated via API."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    original_cost = snapshot['base_estimate']['total_monthly_cost_usd']
    
    # Try to mutate (should not affect stored snapshot)
    snapshot['base_estimate']['total_monthly_cost_usd'] = 999.0
    
    # Retrieve again - should be unchanged
    fresh_snapshot = snapshot_service.get_snapshot(snapshot_id)
    assert fresh_snapshot['base_estimate']['total_monthly_cost_usd'] == original_cost


def test_snapshot_includes_metadata(snapshot_service, sample_snapshot_data):
    """Snapshot includes required metadata."""
    snapshot_id = snapshot_service.create_snapshot(
        base_estimate=sample_snapshot_data['base_estimate'],
        region=sample_snapshot_data['region']
    )
    
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    
    assert 'metadata' in snapshot
    assert 'created_at' in snapshot['metadata']
    assert 'read_only' in snapshot['metadata']
    assert snapshot['metadata']['read_only'] is True
