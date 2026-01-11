"""
Domain models for cost insights and optimization suggestions.
Defines the structure of AI-generated insights.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


# Allowed insight types (strict set)
ALLOWED_INSIGHT_TYPES = {
    "high_cost_driver",
    "region_comparison",
    "scaling_assumption",
    "unpriced_resource",
    "missing_input",
    "general_best_practice"
}


@dataclass
class AffectedResource:
    """Represents a resource affected by an insight."""
    resource_name: str
    terraform_type: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "resource_name": self.resource_name,
            "terraform_type": self.terraform_type,
        }


@dataclass
class Insight:
    """Represents a single cost insight or optimization suggestion."""
    type: str  # Must be one of ALLOWED_INSIGHT_TYPES
    title: str
    description: str
    affected_resources: List[AffectedResource]
    confidence: str  # "high" | "medium" | "low"
    assumptions_referenced: List[str]
    suggestions: List[str]
    disclaimer: str  # Required safety disclaimer
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "affected_resources": [resource.to_dict() for resource in self.affected_resources],
            "confidence": self.confidence,
            "assumptions_referenced": self.assumptions_referenced,
            "suggestions": self.suggestions,
            "disclaimer": self.disclaimer,
        }
    
    def validate(self, known_resources: List[Dict[str, str]]) -> bool:
        """
        Validate that insight references only known resources.
        
        Args:
            known_resources: List of dicts with 'resource_name' and 'terraform_type' keys
        
        Returns:
            True if valid, False otherwise
        """
        # Validate insight type
        if self.type not in ALLOWED_INSIGHT_TYPES:
            return False
        
        # Build set of known resource keys
        known_keys = {
            (r.get("resource_name"), r.get("terraform_type"))
            for r in known_resources
        }
        
        # Validate all affected resources are known
        for resource in self.affected_resources:
            resource_key = (resource.resource_name, resource.terraform_type)
            if resource_key not in known_keys:
                return False
        
        # Validate confidence
        if self.confidence not in ["high", "medium", "low"]:
            return False
        
        # Validate disclaimer exists (safety requirement)
        if not self.disclaimer or len(self.disclaimer.strip()) == 0:
            return False
        
        return True


@dataclass
class InsightResponse:
    """Response containing cost insights."""
    insights: List[Insight]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "insights": [insight.to_dict() for insight in self.insights]
        }
