"""
Cost insights service using Mistral AI.
Generates advisory insights and optimization suggestions.
"""
from typing import Dict, Any, List
import json
import logging

from backend.services.mistral_client import MistralClient, MistralAPIError
from backend.domain.insight_models import Insight, AffectedResource, InsightResponse, ALLOWED_INSIGHT_TYPES
from backend.domain.cost_models import CostEstimate
from backend.domain.scenario_models import ScenarioEstimateResult
from backend.core.config import config


logger = logging.getLogger(__name__)


class CostInsightsError(Exception):
    """Raised when cost insights generation fails."""
    pass


class CostInsightsService:
    """Service for generating cost insights using Mistral AI."""
    
    MAX_INSIGHTS = 10  # Limit total insights
    
    def __init__(self, mistral_client: MistralClient = None):
        """
        Initialize cost insights service.
        
        Args:
            mistral_client: Mistral client instance (creates new if None)
        """
        self.mistral_client = mistral_client or MistralClient()
    
    def _extract_resource_summary(self, estimate: CostEstimate) -> List[Dict[str, Any]]:
        """
        Extract resource summary from cost estimate.
        Only includes visible cost data, no secrets or internals.
        
        Args:
            estimate: Cost estimate
        
        Returns:
            List of resource summaries
        """
        resources = []
        
        for item in estimate.line_items:
            resources.append({
                "resource_name": item.resource_name,
                "terraform_type": item.terraform_type,
                "cloud": item.cloud,
                "service": item.service,
                "region": item.region,
                "monthly_cost_usd": item.monthly_cost_usd,
                "confidence": item.confidence,
                "assumptions": item.assumptions,
            })
        
        return resources
    
    def _build_insights_prompt(
        self,
        intent_graph: Dict[str, Any],
        base_estimate: CostEstimate,
        scenario_result: ScenarioEstimateResult = None
    ) -> str:
        """
        Build prompt for Mistral AI to generate cost insights.
        
        Prompt design principles:
        - Constrain to specific insight types only
        - Reference only visible cost data
        - Never suggest savings amounts
        - Never promise reductions
        - Always include disclaimers
        - Phrase suggestions as questions/investigations
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            base_estimate: Base cost estimate
            scenario_result: Optional scenario comparison result
        
        Returns:
            Formatted prompt string
        """
        # Extract resource summary (visible data only)
        resources = self._extract_resource_summary(base_estimate)
        total_cost = base_estimate.total_monthly_cost_usd
        region = base_estimate.region
        unpriced_count = len(base_estimate.unpriced_resources)
        
        # Build resources summary text
        resources_text = json.dumps(resources, indent=2)
        
        # Build scenario delta text if available
        scenario_text = ""
        if scenario_result:
            deltas_summary = [
                {
                    "resource_name": d.resource_name,
                    "terraform_type": d.terraform_type,
                    "base_cost": d.base_monthly_cost_usd,
                    "scenario_cost": d.scenario_monthly_cost_usd,
                    "delta_usd": d.delta_usd,
                    "delta_percent": d.delta_percent,
                }
                for d in scenario_result.deltas[:5]  # Top 5 deltas
            ]
            scenario_text = f"\n\nSCENARIO COMPARISON:\n{json.dumps(scenario_result.assumptions, indent=2)}\n\nDELTAS:\n{json.dumps(deltas_summary, indent=2)}"
            if scenario_result.region_changed:
                scenario_text += f"\n\nRegion changed: {base_estimate.region} -> {scenario_result.scenario_estimate.region}"
        
        unpriced_text = ""
        if unpriced_count > 0:
            unpriced_resources = [
                {
                    "resource_name": r.resource_name,
                    "terraform_type": r.terraform_type,
                    "reason": r.reason,
                }
                for r in base_estimate.unpriced_resources
            ]
            unpriced_text = f"\n\nUNPRICED RESOURCES:\n{json.dumps(unpriced_resources, indent=2)}"
        
        prompt = f"""You are a cost optimization advisor. Your task is to analyze cost estimates and provide advisory insights ONLY.

CRITICAL RULES:
1. DO NOT calculate or modify costs
2. DO NOT invent savings amounts
3. DO NOT promise cost reductions
4. DO NOT suggest discounts, reserved instances, or savings plans
5. DO NOT recommend destructive actions
6. Reference ONLY the visible cost data provided
7. Phrase suggestions as questions or investigations
8. Always include disclaimers
9. Limit to maximum {self.MAX_INSIGHTS} insights

INPUT DATA:
Base Estimate Total: ${total_cost:.2f}/month
Region: {region}
Resources: {len(resources)}
Unpriced Resources: {unpriced_count}

RESOURCES:
{resources_text}{unpriced_text}{scenario_text}

TASK:
Generate advisory insights to help users understand costs and identify optimization opportunities.

ALLOWED INSIGHT TYPES (ONLY these):
1. high_cost_driver - Resources or services dominating total cost
2. region_comparison - Cost differences between regions (if scenario provided)
3. scaling_assumption - Assumptions about resource counts/scaling
4. unpriced_resource - Resources that couldn't be priced
5. missing_input - Missing information affecting cost certainty
6. general_best_practice - General cost optimization best practices

OUTPUT FORMAT:
Return a valid JSON array with this exact structure:
[
  {{
    "type": "high_cost_driver",
    "title": "EC2 instances dominate monthly cost",
    "description": "EC2 resources account for ~65% of the total estimated monthly cost.",
    "affected_resources": [
      {{
        "resource_name": "web",
        "terraform_type": "aws_instance"
      }}
    ],
    "confidence": "high",
    "assumptions_referenced": [
      "730 hours/month",
      "t3.medium instance type"
    ],
    "suggestions": [
      "Verify whether t3.medium is required for all environments",
      "Consider comparing costs in different regions for non-latency-sensitive workloads"
    ],
    "disclaimer": "This is an assumption-based estimate; validate before making changes."
  }}
]

VALIDATION RULES:
- Each insight must reference at least one resource from the input
- Confidence must be <= lowest confidence of referenced resources
- Suggestions must be phrased as questions or investigations
- Never mention specific savings amounts
- Never promise reductions
- Include disclaimer on every insight
- Maximum {self.MAX_INSIGHTS} insights total

Return ONLY valid JSON array, no markdown, no explanation, no code blocks."""
        
        return prompt
    
    def _validate_insight(self, insight_dict: Dict[str, Any], known_resources: List[Dict[str, str]]) -> bool:
        """
        Validate a single insight.
        
        Args:
            insight_dict: Parsed insight dictionary
            known_resources: List of known resources for validation
        
        Returns:
            True if valid, False otherwise
        """
        try:
            # Validate required fields
            required_fields = [
                "type", "title", "description", "affected_resources",
                "confidence", "assumptions_referenced", "suggestions", "disclaimer"
            ]
            for field in required_fields:
                if field not in insight_dict:
                    return False
            
            # Validate insight type
            if insight_dict["type"] not in ALLOWED_INSIGHT_TYPES:
                return False
            
            # Validate affected resources
            affected_resources = insight_dict["affected_resources"]
            if not isinstance(affected_resources, list) or len(affected_resources) == 0:
                return False
            
            # Validate all affected resources are known
            known_keys = {
                (r.get("resource_name"), r.get("terraform_type"))
                for r in known_resources
            }
            
            for resource in affected_resources:
                if not isinstance(resource, dict):
                    return False
                resource_name = resource.get("resource_name")
                terraform_type = resource.get("terraform_type")
                if (resource_name, terraform_type) not in known_keys:
                    return False
            
            # Validate confidence
            if insight_dict["confidence"] not in ["high", "medium", "low"]:
                return False
            
            # Validate disclaimer exists (safety requirement)
            disclaimer = insight_dict.get("disclaimer", "")
            if not disclaimer or len(disclaimer.strip()) == 0:
                return False
            
            # Reject numeric savings claims (safety)
            description = insight_dict.get("description", "").lower()
            suggestions_text = " ".join(insight_dict.get("suggestions", [])).lower()
            combined_text = (description + " " + suggestions_text).lower()
            
            # Check for savings promises
            savings_keywords = ["save $", "reduce by", "save %", "guaranteed savings"]
            for keyword in savings_keywords:
                if keyword in combined_text:
                    return False
            
            return True
        
        except (TypeError, AttributeError, KeyError):
            return False
    
    async def generate_insights(
        self,
        intent_graph: Dict[str, Any],
        base_estimate: CostEstimate,
        scenario_result: ScenarioEstimateResult = None
    ) -> InsightResponse:
        """
        Generate cost insights using Mistral AI.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            base_estimate: Base cost estimate
            scenario_result: Optional scenario comparison result
        
        Returns:
            InsightResponse with validated insights
        
        Raises:
            CostInsightsError: If insights generation fails
            MistralAPIError: If Mistral API call fails
        """
        # Build prompt
        prompt = self._build_insights_prompt(intent_graph, base_estimate, scenario_result)
        
        # Prepare messages for Mistral API
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        # Call Mistral API with JSON response format enforced
        try:
            response = await self.mistral_client.chat_completion(
                messages=messages,
                temperature=0.2,  # Lower temperature for more deterministic output
                response_format={"type": "json_object"}  # Enforce JSON response
            )
        except MistralAPIError as error:
            raise CostInsightsError(
                f"Failed to generate insights: {str(error)}"
            ) from error
        
        # Extract content from response
        choices = response.get("choices", [])
        if not choices:
            raise CostInsightsError("Empty response from Mistral API")
        
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise CostInsightsError("No content in Mistral API response")
        
        # Parse JSON response
        try:
            # Remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            if content.startswith("```json"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            
            # Try to parse as JSON object first (Mistral may wrap array)
            parsed = json.loads(content)
            
            # Handle both array and object with 'insights' key
            if isinstance(parsed, list):
                insights_array = parsed
            elif isinstance(parsed, dict) and "insights" in parsed:
                insights_array = parsed["insights"]
            else:
                raise ValueError("Invalid response format: expected array or object with 'insights' key")
        
        except json.JSONDecodeError as error:
            raise CostInsightsError(
                f"Failed to parse JSON response from Mistral: {str(error)}"
            ) from error
        
        # Build known resources list for validation
        known_resources = []
        for item in base_estimate.line_items:
            known_resources.append({
                "resource_name": item.resource_name,
                "terraform_type": item.terraform_type,
            })
        for resource in base_estimate.unpriced_resources:
            known_resources.append({
                "resource_name": resource.resource_name,
                "terraform_type": resource.terraform_type,
            })
    
    async def generate_insights_from_dicts(
        self,
        intent_graph: Dict[str, Any],
        base_estimate_dict: Dict[str, Any],
        scenario_result_dict: Dict[str, Any] = None
    ) -> InsightResponse:
        """
        Generate insights from dictionary representations (for API use).
        
        This is a convenience method that reconstructs objects from dicts.
        In production, you might want to use generate_insights with proper objects.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            base_estimate_dict: Base cost estimate dictionary
            scenario_result_dict: Optional scenario comparison result dictionary
        
        Returns:
            InsightResponse with validated insights
        
        Raises:
            CostInsightsError: If insights generation fails
        """
        # This is a simplified version that extracts data from dicts
        # For full implementation, you'd need to reconstruct CostEstimate objects
        # For now, we'll extract what we need from the dicts
        
        resources = self._extract_resource_summary_from_dict(base_estimate_dict)
        total_cost = base_estimate_dict.get("total_monthly_cost_usd", 0)
        region = base_estimate_dict.get("region", "unknown")
        unpriced_count = len(base_estimate_dict.get("unpriced_resources", []))
        
        # Build resources summary text
        resources_text = json.dumps(resources, indent=2)
        
        # Build scenario delta text if available
        scenario_text = ""
        if scenario_result_dict:
            assumptions = scenario_result_dict.get("assumptions", [])
            deltas = scenario_result_dict.get("deltas", [])
            deltas_summary = [
                {
                    "resource_name": d.get("resource_name"),
                    "terraform_type": d.get("terraform_type"),
                    "base_cost": d.get("base_monthly_cost_usd"),
                    "scenario_cost": d.get("scenario_monthly_cost_usd"),
                    "delta_usd": d.get("delta_usd"),
                    "delta_percent": d.get("delta_percent"),
                }
                for d in deltas[:5]  # Top 5 deltas
            ]
            scenario_text = f"\n\nSCENARIO COMPARISON:\n{json.dumps(assumptions, indent=2)}\n\nDELTAS:\n{json.dumps(deltas_summary, indent=2)}"
            if scenario_result_dict.get("region_changed"):
                base_region = base_estimate_dict.get("region", "unknown")
                scenario_estimate = scenario_result_dict.get("scenario_estimate", {})
                scenario_region = scenario_estimate.get("region", "unknown")
                scenario_text += f"\n\nRegion changed: {base_region} -> {scenario_region}"
        
        unpriced_text = ""
        unpriced_resources = base_estimate_dict.get("unpriced_resources", [])
        if unpriced_resources:
            unpriced_list = [
                {
                    "resource_name": r.get("resource_name"),
                    "terraform_type": r.get("terraform_type"),
                    "reason": r.get("reason"),
                }
                for r in unpriced_resources
            ]
            unpriced_text = f"\n\nUNPRICED RESOURCES:\n{json.dumps(unpriced_list, indent=2)}"
        
        # Build prompt (similar to _build_insights_prompt but using dict data)
        prompt = f"""You are a cost optimization advisor. Your task is to analyze cost estimates and provide advisory insights ONLY.

CRITICAL RULES:
1. DO NOT calculate or modify costs
2. DO NOT invent savings amounts
3. DO NOT promise cost reductions
4. DO NOT suggest discounts, reserved instances, or savings plans
5. DO NOT recommend destructive actions
6. Reference ONLY the visible cost data provided
7. Phrase suggestions as questions or investigations
8. Always include disclaimers
9. Limit to maximum {self.MAX_INSIGHTS} insights

INPUT DATA:
Base Estimate Total: ${total_cost:.2f}/month
Region: {region}
Resources: {len(resources)}
Unpriced Resources: {unpriced_count}

RESOURCES:
{resources_text}{unpriced_text}{scenario_text}

TASK:
Generate advisory insights to help users understand costs and identify optimization opportunities.

ALLOWED INSIGHT TYPES (ONLY these):
1. high_cost_driver - Resources or services dominating total cost
2. region_comparison - Cost differences between regions (if scenario provided)
3. scaling_assumption - Assumptions about resource counts/scaling
4. unpriced_resource - Resources that couldn't be priced
5. missing_input - Missing information affecting cost certainty
6. general_best_practice - General cost optimization best practices

OUTPUT FORMAT:
Return a valid JSON array with this exact structure:
[
  {{
    "type": "high_cost_driver",
    "title": "EC2 instances dominate monthly cost",
    "description": "EC2 resources account for ~65% of the total estimated monthly cost.",
    "affected_resources": [
      {{
        "resource_name": "web",
        "terraform_type": "aws_instance"
      }}
    ],
    "confidence": "high",
    "assumptions_referenced": [
      "730 hours/month",
      "t3.medium instance type"
    ],
    "suggestions": [
      "Verify whether t3.medium is required for all environments",
      "Consider comparing costs in different regions for non-latency-sensitive workloads"
    ],
    "disclaimer": "This is an assumption-based estimate; validate before making changes."
  }}
]

VALIDATION RULES:
- Each insight must reference at least one resource from the input
- Confidence must be <= lowest confidence of referenced resources
- Suggestions must be phrased as questions or investigations
- Never mention specific savings amounts
- Never promise reductions
- Include disclaimer on every insight
- Maximum {self.MAX_INSIGHTS} insights total

Return ONLY valid JSON array, no markdown, no explanation, no code blocks."""
        
        # Call Mistral API
        messages = [{"role": "user", "content": prompt}]
        
        try:
            response = await self.mistral_client.chat_completion(
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
        except MistralAPIError as error:
            raise CostInsightsError(
                f"Failed to generate insights: {str(error)}"
            ) from error
        
        # Extract and parse response (same logic as generate_insights)
        choices = response.get("choices", [])
        if not choices:
            raise CostInsightsError("Empty response from Mistral API")
        
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise CostInsightsError("No content in Mistral API response")
        
        try:
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            if content.startswith("```json"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            
            parsed = json.loads(content)
            
            if isinstance(parsed, list):
                insights_array = parsed
            elif isinstance(parsed, dict) and "insights" in parsed:
                insights_array = parsed["insights"]
            else:
                raise ValueError("Invalid response format: expected array or object with 'insights' key")
        
        except json.JSONDecodeError as error:
            raise CostInsightsError(
                f"Failed to parse JSON response from Mistral: {str(error)}"
            ) from error
        
        # Build known resources list for validation
        known_resources = []
        for item in resources:
            known_resources.append({
                "resource_name": item.get("resource_name"),
                "terraform_type": item.get("terraform_type"),
            })
        for resource in unpriced_resources:
            known_resources.append({
                "resource_name": resource.get("resource_name"),
                "terraform_type": resource.get("terraform_type"),
            })
        
        # Validate and convert insights (same logic as generate_insights)
        validated_insights = []
        for insight_dict in insights_array[:self.MAX_INSIGHTS]:
            if not isinstance(insight_dict, dict):
                continue
            
            if not self._validate_insight(insight_dict, known_resources):
                logger.warning(f"Skipping invalid insight: {insight_dict.get('title', 'unknown')}")
                continue
            
            affected_resources = [
                AffectedResource(
                    resource_name=r.get("resource_name"),
                    terraform_type=r.get("terraform_type")
                )
                for r in insight_dict.get("affected_resources", [])
            ]
            
            insight = Insight(
                type=insight_dict["type"],
                title=insight_dict["title"],
                description=insight_dict["description"],
                affected_resources=affected_resources,
                confidence=insight_dict["confidence"],
                assumptions_referenced=insight_dict.get("assumptions_referenced", []),
                suggestions=insight_dict.get("suggestions", []),
                disclaimer=insight_dict["disclaimer"],
            )
            
            validated_insights.append(insight)
        
        # Deduplicate
        seen = set()
        deduplicated = []
        for insight in validated_insights:
            key = (insight.type, insight.title.lower())
            if key not in seen:
                seen.add(key)
                deduplicated.append(insight)
        
        return InsightResponse(insights=deduplicated[:self.MAX_INSIGHTS])
        
        # Validate and convert insights
        validated_insights = []
        for insight_dict in insights_array[:self.MAX_INSIGHTS]:  # Limit to max
            if not isinstance(insight_dict, dict):
                continue
            
            # Validate insight
            if not self._validate_insight(insight_dict, known_resources):
                logger.warning(f"Skipping invalid insight: {insight_dict.get('title', 'unknown')}")
                continue
            
            # Build AffectedResource objects
            affected_resources = [
                AffectedResource(
                    resource_name=r.get("resource_name"),
                    terraform_type=r.get("terraform_type")
                )
                for r in insight_dict.get("affected_resources", [])
            ]
            
            # Build Insight object
            insight = Insight(
                type=insight_dict["type"],
                title=insight_dict["title"],
                description=insight_dict["description"],
                affected_resources=affected_resources,
                confidence=insight_dict["confidence"],
                assumptions_referenced=insight_dict.get("assumptions_referenced", []),
                suggestions=insight_dict.get("suggestions", []),
                disclaimer=insight_dict["disclaimer"],
            )
            
            validated_insights.append(insight)
        
        # Deduplicate insights by type and title
        seen = set()
        deduplicated = []
        for insight in validated_insights:
            key = (insight.type, insight.title.lower())
            if key not in seen:
                seen.add(key)
                deduplicated.append(insight)
        
        return InsightResponse(insights=deduplicated[:self.MAX_INSIGHTS])
