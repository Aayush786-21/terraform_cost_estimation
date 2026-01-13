"""
Share API endpoints for read-only snapshot links.
"""

import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.services.snapshot_service import get_snapshot_service


router = APIRouter(prefix="/api/share", tags=["share"])


class ShareRequest(BaseModel):
    """Request model for creating a share snapshot."""
    base_estimate: Dict[str, Any]
    scenario_estimate: Optional[Dict[str, Any]] = None
    deltas: Optional[List[Dict[str, Any]]] = None
    insights: Optional[List[Dict[str, Any]]] = None
    scenario_label: Optional[str] = None
    region: Optional[str] = None


class ShareResponse(BaseModel):
    """Response model for share creation."""
    status: str
    share_url: str
    snapshot_id: str


class SnapshotResponse(BaseModel):
    """Response model for snapshot retrieval."""
    status: str
    snapshot: Dict[str, Any]


@router.post("", response_model=ShareResponse)
async def create_share(request: ShareRequest, http_request: Request):
    """
    Create a read-only snapshot and return a shareable URL.
    
    The snapshot will expire after 24 hours.
    """
    try:
        snapshot_service = get_snapshot_service()
        
        snapshot_id = snapshot_service.create_snapshot(
            base_estimate=request.base_estimate,
            scenario_estimate=request.scenario_estimate,
            deltas=request.deltas,
            insights=request.insights,
            scenario_label=request.scenario_label,
            region=request.region
        )
        
        # Get base URL from request or environment
        base_url = os.getenv('BASE_URL')
        if not base_url:
            # Construct from request
            scheme = http_request.url.scheme
            host = http_request.url.hostname
            port = http_request.url.port
            if port and port not in (80, 443):
                base_url = f"{scheme}://{host}:{port}"
            else:
                base_url = f"{scheme}://{host}"
        
        # Use main page with share query parameter for single-page app
        share_url = f"{base_url}/?share={snapshot_id}"
        
        return ShareResponse(
            status="ok",
            share_url=share_url,
            snapshot_id=snapshot_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create snapshot: {str(e)}"
        )


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_share(snapshot_id: str):
    """
    Retrieve a snapshot by ID.
    
    Returns 404 if not found or expired.
    """
    snapshot_service = get_snapshot_service()
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail="Snapshot not found or expired"
        )
    
    return SnapshotResponse(
        status="ok",
        snapshot=snapshot
    )
