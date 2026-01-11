"""
Domain models for scenario modeling and delta comparison.
Defines scenario inputs and comparison results.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from backend.domain.cost_models import CostEstimate


@dataclass
class ScenarioInput:
    """Input parameters for scenario modeling."""
    region_override: Optional[str] = None
    autoscaling_average_override: Optional[int] = None
    users: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {}
        if self.region_override is not None:
            result["region_override"] = self.region_override
        if self.autoscaling_average_override is not None:
            result["autoscaling_average_override"] = self.autoscaling_average_override
        if self.users is not None:
            result["users"] = self.users
        return result


@dataclass
class ScenarioDeltaLineItem:
    """Represents the delta for a single resource between base and scenario."""
    resource_name: str
    terraform_type: str
    base_monthly_cost_usd: float
    scenario_monthly_cost_usd: float
    delta_usd: float
    delta_percent: Optional[float]  # None if base_cost == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "resource_name": self.resource_name,
            "terraform_type": self.terraform_type,
            "base_monthly_cost_usd": round(self.base_monthly_cost_usd, 2),
            "scenario_monthly_cost_usd": round(self.scenario_monthly_cost_usd, 2),
            "delta_usd": round(self.delta_usd, 2),
        }
        if self.delta_percent is not None:
            result["delta_percent"] = round(self.delta_percent, 1)
        else:
            result["delta_percent"] = None
        return result


@dataclass
class ScenarioEstimateResult:
    """Result of scenario modeling comparison."""
    base_estimate: CostEstimate
    scenario_estimate: CostEstimate
    deltas: List[ScenarioDeltaLineItem]
    region_changed: bool
    assumptions: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        # Sort deltas by absolute delta_usd descending
        sorted_deltas = sorted(
            self.deltas,
            key=lambda x: abs(x.delta_usd),
            reverse=True
        )
        
        return {
            "region_changed": self.region_changed,
            "assumptions": self.assumptions,
            "base_estimate": self.base_estimate.to_dict(),
            "scenario_estimate": self.scenario_estimate.to_dict(),
            "deltas": [delta.to_dict() for delta in sorted_deltas],
        }
