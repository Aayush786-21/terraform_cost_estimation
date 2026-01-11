"""
Domain models for cost estimation.
Defines the structure of cost estimates and line items.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CostLineItem:
    """Represents a single cost line item for a resource."""
    cloud: str
    service: str
    resource_name: str
    terraform_type: str
    region: str
    monthly_cost_usd: float
    pricing_unit: str  # e.g., "hour", "GB-month", "request"
    assumptions: List[str]
    priced: bool
    confidence: str  # "high" | "medium" | "low"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "cloud": self.cloud,
            "service": self.service,
            "resource_name": self.resource_name,
            "terraform_type": self.terraform_type,
            "region": self.region,
            "monthly_cost_usd": round(self.monthly_cost_usd, 2),
            "pricing_unit": self.pricing_unit,
            "assumptions": self.assumptions,
            "priced": self.priced,
            "confidence": self.confidence,
        }


@dataclass
class UnpricedResource:
    """Represents a resource that could not be priced."""
    resource_name: str
    terraform_type: str
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "resource_name": self.resource_name,
            "terraform_type": self.terraform_type,
            "reason": self.reason,
        }


@dataclass
class CostEstimate:
    """Represents a complete cost estimate."""
    currency: str
    total_monthly_cost_usd: float
    line_items: List[CostLineItem]
    unpriced_resources: List[UnpricedResource]
    region: str
    pricing_timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        # Sort line items by monthly_cost_usd descending
        sorted_items = sorted(
            self.line_items,
            key=lambda x: x.monthly_cost_usd,
            reverse=True
        )
        
        return {
            "currency": self.currency,
            "total_monthly_cost_usd": round(self.total_monthly_cost_usd, 2),
            "region": self.region,
            "pricing_timestamp": self.pricing_timestamp.isoformat(),
            "line_items": [item.to_dict() for item in sorted_items],
            "unpriced_resources": [resource.to_dict() for resource in self.unpriced_resources],
        }
