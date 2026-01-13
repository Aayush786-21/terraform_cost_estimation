"""
Cost estimator service.
Converts intent graph into cost estimates using official pricing APIs.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging

from backend.domain.cost_models import CostEstimate, CostLineItem, UnpricedResource
from backend.domain.scenario_models import ScenarioInput, ScenarioDeltaLineItem, ScenarioEstimateResult
from backend.pricing.aws_pricing_client import AWSPricingClient, AWSPricingError
from backend.pricing.azure_pricing_client import AzurePricingClient, AzurePricingError
from backend.pricing.gcp_pricing_client import GCPPricingClient, GCPPricingError
from backend.core.config import config


logger = logging.getLogger(__name__)


class CostEstimatorError(Exception):
    """Raised when cost estimation fails."""
    pass


class CostEstimator:
    """Service for estimating costs from Terraform intent graph."""
    
    def __init__(
        self,
        aws_client: AWSPricingClient = None,
        azure_client: AzurePricingClient = None,
        gcp_client: GCPPricingClient = None
    ):
        """
        Initialize cost estimator with pricing clients.
        
        This constructor is intentionally defensive:
        - If a cloud pricing client cannot be initialized (e.g. missing SDK,
          no network, or credentials issues), we log the problem and fall back
          to static baseline prices for common instance types instead of
          failing the entire estimate.
        - This keeps the product usable in local/demo environments while still
          using official pricing APIs when available.
        
        Args:
            aws_client: AWS pricing client (creates new if None)
            azure_client: Azure pricing client (creates new if None)
            gcp_client: GCP pricing client (creates new if None)
        """
        # AWS client (may fallback to static pricing)
        if aws_client is not None:
            self.aws_client = aws_client
        else:
            try:
                self.aws_client = AWSPricingClient()
            except AWSPricingError as error:
                logger.warning(
                    "AWS pricing client unavailable, falling back to static pricing: %s",
                    error,
                )
                self.aws_client = None

        # Azure client (may fallback to static pricing)
        if azure_client is not None:
            self.azure_client = azure_client
        else:
            try:
                self.azure_client = AzurePricingClient()
            except AzurePricingError as error:
                logger.warning(
                    "Azure pricing client unavailable, falling back to static pricing: %s",
                    error,
                )
                self.azure_client = None

        # GCP client (currently a placeholder; pricing not fully implemented)
        try:
            self.gcp_client = gcp_client or GCPPricingClient()
        except GCPPricingError as error:
            logger.warning(
                "GCP pricing client unavailable (pricing not yet implemented): %s",
                error,
            )
            self.gcp_client = None
    
    def _resolve_region(
        self,
        region_info: Dict[str, Any],
        region_override: Optional[str] = None
    ) -> Tuple[str, List[str]]:
        """
        Resolve region from region_info, with optional override.
        
        Args:
            region_info: Region info from intent graph
            region_override: Optional region override from request
        
        Returns:
            Tuple of (resolved_region, assumptions_list)
        """
        assumptions = []
        
        if region_override:
            assumptions.append(f"Region overridden to {region_override}")
            return region_override, assumptions
        
        region_source = region_info.get("source", "unknown")
        region_value = region_info.get("value")
        
        # Handle explicit region (from resource) or provider_default (from provider config)
        if region_source in ["explicit", "provider_default"] and region_value:
            if region_source == "provider_default":
                assumptions.append(f"Region from provider config: {region_value}")
            return region_value, assumptions
        
        # Default region based on cloud provider
        # Could be enhanced to detect from provider config
        default_region = "us-east-1"  # Conservative default
        assumptions.append(f"Region not specified, using default: {default_region}")
        return default_region, assumptions
    
    def _resolve_count(
        self,
        count_model: Dict[str, Any],
        autoscaling_average_override: Optional[int] = None
    ) -> Tuple[Optional[int], List[str]]:
        """
        Resolve resource count from count_model.
        
        Args:
            count_model: Count model from intent graph
            autoscaling_average_override: Optional override for autoscaling average
        
        Returns:
            Tuple of (count_value, assumptions_list)
        """
        assumptions = []
        count_type = count_model.get("type", "unknown")
        
        if count_type == "fixed":
            value = count_model.get("value")
            if value is not None:
                return int(value), assumptions
            assumptions.append("Fixed count value is unknown")
            return None, assumptions
        
        elif count_type == "autoscaling":
            if autoscaling_average_override is not None:
                assumptions.append(f"Using provided autoscaling average: {autoscaling_average_override}")
                return autoscaling_average_override, assumptions
            
            # Try to use average of min/max if available
            min_val = count_model.get("min")
            max_val = count_model.get("max")
            if min_val is not None and max_val is not None:
                average = (min_val + max_val) / 2
                assumptions.append(f"Autoscaling: using average of min/max: {average}")
                return int(average), assumptions
            
            assumptions.append("Autoscaling: cannot determine average count")
            return None, assumptions
        
        else:
            assumptions.append(f"Count type '{count_type}' cannot be resolved")
            return None, assumptions
    
    async def _price_aws_resource(
        self,
        resource: Dict[str, Any],
        resolved_region: str,
        resolved_count: int,
        assumptions: List[str]
    ) -> Optional[CostLineItem]:
        """
        Price an AWS resource.
        
        Args:
            resource: Resource from intent graph
            resolved_region: Resolved region
            resolved_count: Resolved resource count
            assumptions: List of assumptions (mutated)
        
        Returns:
            CostLineItem if priced, None otherwise
        """
        service = resource.get("service", "")
        terraform_type = resource.get("terraform_type", "")
        resource_name = resource.get("name", "unknown")
        size_hint = resource.get("size", {})
        usage = resource.get("usage", {})
        count_model = resource.get("count_model", {})
        confidence = count_model.get("confidence", "low")
        
        # Handle free/low-cost networking resources (these don't have instance_type)
        free_networking_resources = {
            "aws_vpc": ("VPC", "Free - VPCs have no charge"),
            "aws_subnet": ("VPC", "Free - Subnets have no charge"),
            "aws_internet_gateway": ("VPC", "Free - Internet gateways have no charge"),
            "aws_route_table": ("VPC", "Free - Route tables have no charge"),
            "aws_route_table_association": ("VPC", "Free - Route table associations have no charge"),
            "aws_security_group": ("EC2", "Free - Security groups have no charge"),
            "aws_security_group_rule": ("EC2", "Free - Security group rules have no charge"),
        }
        
        if terraform_type in free_networking_resources:
            service_name, reason = free_networking_resources[terraform_type]
            assumptions.append(reason)
            return CostLineItem(
                cloud="aws",
                service=service_name,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=0.0,
                pricing_unit="month",
                assumptions=assumptions,
                priced=True,
                confidence="high"
            )
        
        # Extract instance type or SKU
        instance_type = size_hint.get("instance_type") or size_hint.get("sku")
        if not instance_type:
            return None
        
        # Baseline fallback prices for common instance types (approximate).
        # These are used when real pricing APIs are unavailable so that local
        # demos still show non-zero costs.
        fallback_ec2_prices = {
            "t3.nano": 0.005,
            "t3.micro": 0.01,
            "t3.small": 0.02,
            "t3.medium": 0.04,
            "t3.large": 0.08,
        }
        fallback_rds_prices = {
            "db.t3.micro": 0.02,
            "db.t3.small": 0.04,
            "db.t3.medium": 0.08,
        }

        # Determine pricing unit and calculate
        hours_per_month = usage.get("hours_per_month", config.HOURS_PER_MONTH)
        assumptions.append(f"{hours_per_month} hours/month")

        def _fallback_hourly_price() -> Optional[float]:
            """Static demo prices used when official pricing is unavailable."""
            if "EC2" in service or terraform_type == "aws_instance":
                price = fallback_ec2_prices.get(instance_type)
                if price is not None:
                    assumptions.append(
                        f"Using static demo price for EC2 instance_type={instance_type}"
                    )
                return price
            if "RDS" in service or terraform_type.startswith("aws_db"):
                price = fallback_rds_prices.get(instance_type)
                if price is not None:
                    assumptions.append(
                        f"Using static demo price for RDS instance_class={instance_type}"
                    )
                return price
            return None
        
        try:
            hourly_price: Optional[float] = None
            
            # Route to appropriate pricing method if client is available
            if self.aws_client is not None:
                if "EC2" in service or terraform_type == "aws_instance":
                    hourly_price = await self.aws_client.get_ec2_instance_price(
                        instance_type=instance_type,
                        region=resolved_region
                    )
                elif "RDS" in service or terraform_type.startswith("aws_db"):
                    hourly_price = await self.aws_client.get_rds_instance_price(
                        instance_type=instance_type,
                        region=resolved_region
                    )

            # Fallback to static pricing if API client is missing or returned no price
            if hourly_price is None:
                hourly_price = _fallback_hourly_price()
            
            if hourly_price is None:
                return None
            
            # Calculate monthly cost
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(f"${hourly_price:.4f}/hour × {resolved_count} instances")
            
            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        
        except AWSPricingError as error:
            logger.warning(f"Failed to price AWS resource {resource_name}: {error}")
            # Final fallback
            hourly_price = _fallback_hourly_price()
            if hourly_price is None:
                return None
            
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(
                f"Fallback static price used after AWS pricing error: ${hourly_price:.4f}/hour × {resolved_count} instances"
            )
            
            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        except Exception as error:
            # Catch any unexpected errors during pricing
            logger.error(
                f"Unexpected error pricing AWS resource {resource_name} ({terraform_type}): {type(error).__name__}: {error}", 
                exc_info=True
            )
            hourly_price = _fallback_hourly_price()
            if hourly_price is None:
                return None

            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(
                f"Fallback static price used after unexpected error: ${hourly_price:.4f}/hour × {resolved_count} instances"
            )

            return CostLineItem(
                cloud="aws",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
    
    async def _price_azure_resource(
        self,
        resource: Dict[str, Any],
        resolved_region: str,
        resolved_count: int,
        assumptions: List[str]
    ) -> Optional[CostLineItem]:
        """
        Price an Azure resource.
        
        Args:
            resource: Resource from intent graph
            resolved_region: Resolved region
            resolved_count: Resolved resource count
            assumptions: List of assumptions (mutated)
        
        Returns:
            CostLineItem if priced, None otherwise
        """
        service = resource.get("service", "")
        terraform_type = resource.get("terraform_type", "")
        resource_name = resource.get("name", "unknown")
        size_hint = resource.get("size", {})
        usage = resource.get("usage", {})
        count_model = resource.get("count_model", {})
        confidence = count_model.get("confidence", "low")
        
        sku_name = size_hint.get("sku") or size_hint.get("instance_type")
        if not sku_name:
            return None
        
        hours_per_month = usage.get("hours_per_month", config.HOURS_PER_MONTH)
        assumptions.append(f"{hours_per_month} hours/month")
        
        try:
            hourly_price = await self.azure_client.get_virtual_machine_price(
                sku_name=sku_name,
                region=resolved_region
            )
            
            if hourly_price is None:
                return None
            
            monthly_cost = hourly_price * hours_per_month * resolved_count
            assumptions.append(f"${hourly_price:.4f}/hour × {resolved_count} instances")
            
            return CostLineItem(
                cloud="azure",
                service=service,
                resource_name=resource_name,
                terraform_type=terraform_type,
                region=resolved_region,
                monthly_cost_usd=monthly_cost,
                pricing_unit="hour",
                assumptions=assumptions,
                priced=True,
                confidence=confidence
            )
        
        except AzurePricingError as error:
            logger.warning(f"Failed to price Azure resource {resource_name}: {error}")
            return None
    
    async def estimate(
        self,
        intent_graph: Dict[str, Any],
        region_override: Optional[str] = None,
        autoscaling_average_override: Optional[int] = None
    ) -> CostEstimate:
        """
        Estimate costs from intent graph.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            region_override: Optional region override
            autoscaling_average_override: Optional autoscaling average override
        
        Returns:
            CostEstimate with line items and unpriced resources
        
        Raises:
            CostEstimatorError: If estimation fails
        """
        resources = intent_graph.get("resources", [])
        if not resources:
            raise CostEstimatorError("Intent graph has no resources")
        
        line_items: List[CostLineItem] = []
        unpriced_resources: List[UnpricedResource] = []
        
        for resource in resources:
            cloud = resource.get("cloud", "unknown")
            resource_name = resource.get("name", "unknown")
            terraform_type = resource.get("terraform_type", "unknown")
            region_info = resource.get("region", {})
            count_model = resource.get("count_model", {})
            
            # Resolve region
            resolved_region, region_assumptions = self._resolve_region(
                region_info,
                region_override
            )
            
            # Resolve count
            resolved_count, count_assumptions = self._resolve_count(
                count_model,
                autoscaling_average_override
            )
            
            if resolved_count is None:
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Cannot resolve resource count"
                ))
                continue
            
            # Collect assumptions
            assumptions = region_assumptions + count_assumptions
            
            # Price resource based on cloud provider
            line_item = None
            
            try:
                if cloud == "aws":
                    line_item = await self._price_aws_resource(
                        resource,
                        resolved_region,
                        resolved_count,
                        assumptions
                    )
                elif cloud == "azure":
                    line_item = await self._price_azure_resource(
                        resource,
                        resolved_region,
                        resolved_count,
                        assumptions
                    )
                elif cloud == "gcp":
                    # GCP pricing not fully implemented
                    unpriced_resources.append(UnpricedResource(
                        resource_name=resource_name,
                        terraform_type=terraform_type,
                        reason="GCP pricing not fully implemented"
                    ))
                    continue
                else:
                    unpriced_resources.append(UnpricedResource(
                        resource_name=resource_name,
                        terraform_type=terraform_type,
                        reason=f"Cloud provider '{cloud}' not supported for pricing"
                    ))
                    continue
            except (AWSPricingError, AzurePricingError, GCPPricingError) as error:
                # Expected pricing errors - mark as unpriced
                logger.warning(f"Pricing error for {resource_name} ({terraform_type}): {error}")
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason=f"Pricing lookup failed: {str(error)}"
                ))
                continue
            except Exception as error:
                # Unexpected errors during pricing - mark as unpriced rather than failing
                logger.error(f"Unexpected error pricing {resource_name} ({terraform_type}): {type(error).__name__}: {error}", 
                           exc_info=True)
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Unexpected error during pricing lookup"
                ))
                continue
            
            if line_item:
                line_items.append(line_item)
            else:
                unpriced_resources.append(UnpricedResource(
                    resource_name=resource_name,
                    terraform_type=terraform_type,
                    reason="Pricing not available for this resource type"
                ))
        
        # Calculate total
        total_monthly_cost = sum(item.monthly_cost_usd for item in line_items)
        
        # Use first priced resource's region, or default
        region = line_items[0].region if line_items else (region_override or "us-east-1")
        
        # Determine coverage status for each cloud provider
        coverage = self._calculate_coverage(resources, line_items, unpriced_resources)
        
        return CostEstimate(
            currency="USD",
            total_monthly_cost_usd=total_monthly_cost,
            line_items=line_items,
            unpriced_resources=unpriced_resources,
            region=region,
            pricing_timestamp=datetime.now(),
            coverage=coverage
        )
    
    def _calculate_coverage(
        self,
        resources: List[Dict[str, Any]],
        line_items: List[CostLineItem],
        unpriced_resources: List[UnpricedResource]
    ) -> Dict[str, str]:
        """
        Calculate coverage status for each cloud provider.
        
        Args:
            resources: All resources from intent graph
            line_items: Successfully priced resources
            unpriced_resources: Resources that couldn't be priced
        
        Returns:
            Dictionary mapping cloud provider to coverage status
        """
        coverage = {
            "aws": "partial",
            "azure": "partial",
            "gcp": "not_supported_yet"
        }
        
        # Count resources by cloud
        cloud_resources: Dict[str, int] = {}
        cloud_priced: Dict[str, int] = {}
        
        for resource in resources:
            cloud = resource.get("cloud", "unknown")
            if cloud in ["aws", "azure", "gcp"]:
                cloud_resources[cloud] = cloud_resources.get(cloud, 0) + 1
        
        for item in line_items:
            cloud = item.cloud
            if cloud in ["aws", "azure", "gcp"]:
                cloud_priced[cloud] = cloud_priced.get(cloud, 0) + 1
        
        # Update coverage status
        for cloud in ["aws", "azure", "gcp"]:
            total = cloud_resources.get(cloud, 0)
            priced = cloud_priced.get(cloud, 0)
            
            if cloud == "gcp":
                coverage[cloud] = "not_supported_yet"
            elif total == 0:
                # No resources for this cloud
                continue
            elif priced == total:
                coverage[cloud] = "full"
            elif priced > 0:
                coverage[cloud] = "partial"
            else:
                coverage[cloud] = "partial"  # Attempted but no prices found
        
        return coverage
    
    async def estimate_with_scenario(
        self,
        intent_graph: Dict[str, Any],
        scenario_input: ScenarioInput
    ) -> ScenarioEstimateResult:
        """
        Estimate costs with scenario modeling.
        
        Runs base estimate, then scenario estimate with overrides,
        and calculates deltas between them.
        
        Args:
            intent_graph: Intent graph from Terraform interpreter
            scenario_input: Scenario input parameters (overrides)
        
        Returns:
            ScenarioEstimateResult with base, scenario, and deltas
        
        Raises:
            CostEstimatorError: If estimation fails
        """
        # Run base estimate (existing logic)
        base_estimate = await self.estimate(
            intent_graph=intent_graph,
            region_override=None,
            autoscaling_average_override=None
        )
        
        # Build assumptions list
        assumptions = []
        
        # Run scenario estimate with overrides
        scenario_region_override = scenario_input.region_override
        scenario_autoscaling_override = scenario_input.autoscaling_average_override
        
        # Track if region changed
        region_changed = False
        if scenario_region_override and scenario_region_override != base_estimate.region:
            region_changed = True
            assumptions.append(
                f"Region overridden from {base_estimate.region} to {scenario_region_override}"
            )
        
        if scenario_autoscaling_override is not None:
            assumptions.append(
                f"Autoscaling average overridden to {scenario_autoscaling_override} instances"
            )
        
        if scenario_input.users is not None:
            assumptions.append(
                f"Users overridden to {scenario_input.users}"
            )
            # Note: User multiplier logic would be applied here for request-based services
            # Currently not implemented as per requirements
        
        # Run scenario estimate
        scenario_estimate = await self.estimate(
            intent_graph=intent_graph,
            region_override=scenario_region_override,
            autoscaling_average_override=scenario_autoscaling_override
        )
        
        # Calculate deltas
        deltas = self._calculate_deltas(
            base_estimate.line_items,
            scenario_estimate.line_items
        )
        
        return ScenarioEstimateResult(
            base_estimate=base_estimate,
            scenario_estimate=scenario_estimate,
            deltas=deltas,
            region_changed=region_changed,
            assumptions=assumptions
        )
    
    def _calculate_deltas(
        self,
        base_line_items: List[CostLineItem],
        scenario_line_items: List[CostLineItem]
    ) -> List[ScenarioDeltaLineItem]:
        """
        Calculate deltas between base and scenario line items.
        
        Matches resources by resource_name + terraform_type.
        If a resource exists in base but not scenario (unpriced), delta is null.
        If a resource exists in scenario but not base, it's included with base_cost = 0.
        
        Args:
            base_line_items: Base estimate line items
            scenario_line_items: Scenario estimate line items
        
        Returns:
            List of ScenarioDeltaLineItem
        """
        # Build lookup maps for efficient matching
        base_map = {
            (item.resource_name, item.terraform_type): item
            for item in base_line_items
        }
        scenario_map = {
            (item.resource_name, item.terraform_type): item
            for item in scenario_line_items
        }
        
        # Collect all unique resource keys
        all_keys = set(base_map.keys()) | set(scenario_map.keys())
        
        deltas = []
        
        for resource_key in all_keys:
            resource_name, terraform_type = resource_key
            base_item = base_map.get(resource_key)
            scenario_item = scenario_map.get(resource_key)
            
            # Skip if both are missing (shouldn't happen)
            if not base_item and not scenario_item:
                continue
            
            # Get costs (0 if missing)
            base_cost = base_item.monthly_cost_usd if base_item else 0.0
            scenario_cost = scenario_item.monthly_cost_usd if scenario_item else 0.0
            
            # Calculate delta
            delta_usd = scenario_cost - base_cost
            
            # Calculate delta percentage
            delta_percent = None
            if base_cost > 0:
                delta_percent = (delta_usd / base_cost) * 100
            
            deltas.append(ScenarioDeltaLineItem(
                resource_name=resource_name,
                terraform_type=terraform_type,
                base_monthly_cost_usd=base_cost,
                scenario_monthly_cost_usd=scenario_cost,
                delta_usd=delta_usd,
                delta_percent=delta_percent
            ))
        
        return deltas
