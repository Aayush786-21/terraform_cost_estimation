"""
Snapshot service for read-only share links.

Stores estimate snapshots in-memory with TTL expiration.
"""

import uuid
import time
import copy
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class SnapshotService:
    """
    In-memory snapshot storage with TTL.
    
    Snapshots expire after 24 hours.
    """
    
    def __init__(self, ttl_hours: int = 24):
        """
        Initialize snapshot service.
        
        Args:
            ttl_hours: Time-to-live in hours (default: 24)
        """
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = ttl_hours * 3600
        self._cleanup_interval = 3600  # Clean up every hour
        self._last_cleanup = time.time()
    
    def create_snapshot(
        self,
        base_estimate: Dict[str, Any],
        scenario_estimate: Optional[Dict[str, Any]] = None,
        deltas: Optional[list] = None,
        insights: Optional[list] = None,
        scenario_label: Optional[str] = None,
        region: Optional[str] = None
    ) -> str:
        """
        Create a new snapshot.
        
        Args:
            base_estimate: Base cost estimate data
            scenario_estimate: Optional scenario estimate data
            deltas: Optional delta calculations
            insights: Optional AI insights
            scenario_label: Optional scenario description
            region: Optional region identifier
            
        Returns:
            snapshot_id: Unique identifier for the snapshot
        """
        # Generate cryptographically random ID
        snapshot_id = str(uuid.uuid4())
        
        # Create snapshot object
        snapshot = {
            'snapshot_id': snapshot_id,
            'base_estimate': base_estimate,
            'scenario_estimate': scenario_estimate,
            'deltas': deltas,
            'insights': insights,
            'metadata': {
                'created_at': datetime.utcnow().isoformat(),
                'region': region,
                'scenario_label': scenario_label,
                'read_only': True,
                'expires_at': (datetime.utcnow() + timedelta(seconds=self._ttl_seconds)).isoformat()
            }
        }
        
        # Store snapshot (deep copy to ensure immutability)
        self._snapshots[snapshot_id] = copy.deepcopy(snapshot)
        
        # Periodic cleanup
        self._maybe_cleanup()
        
        return snapshot_id
    
    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a snapshot by ID.
        
        Args:
            snapshot_id: Snapshot identifier
        
        Returns:
            Snapshot data if found and not expired, None otherwise (deep copy for immutability)
        """
        # Cleanup expired snapshots first
        self._maybe_cleanup()
        
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            return None
        
        # Check if expired
        expires_at = datetime.fromisoformat(snapshot['metadata']['expires_at'])
        if datetime.utcnow() > expires_at:
            # Remove expired snapshot
            del self._snapshots[snapshot_id]
            return None
        
        # Return deep copy to ensure immutability
        return copy.deepcopy(snapshot)
    
    def _maybe_cleanup(self):
        """
        Clean up expired snapshots periodically.
        """
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        current_time = datetime.utcnow()
        
        expired_ids = []
        for snapshot_id, snapshot in self._snapshots.items():
            expires_at = datetime.fromisoformat(snapshot['metadata']['expires_at'])
            if current_time > expires_at:
                expired_ids.append(snapshot_id)
        
        for snapshot_id in expired_ids:
            del self._snapshots[snapshot_id]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get service statistics (for debugging/monitoring).
        
        Returns:
            Dictionary with stats
        """
        self._maybe_cleanup()
        return {
            'total_snapshots': len(self._snapshots),
            'ttl_hours': self._ttl_seconds / 3600
        }


# Global singleton instance
_snapshot_service: Optional[SnapshotService] = None


def get_snapshot_service() -> SnapshotService:
    """
    Get the global snapshot service instance.
    
    Returns:
        SnapshotService instance
    """
    global _snapshot_service
    if _snapshot_service is None:
        _snapshot_service = SnapshotService()
    return _snapshot_service
