"""
AWS Pricing API client.
Uses boto3 to query official AWS Price List API.
"""
from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:
    boto3 = None

from backend.core.config import config


logger = logging.getLogger(__name__)


class AWSPricingError(Exception):
    """Raised when AWS pricing lookup fails."""
    pass


class AWSPricingClient:
    """Client for querying AWS pricing using boto3."""
    
    # In-memory cache: (service_code, instance_type, region) -> (price, timestamp)
    _cache: Dict[str, tuple] = {}
    
    def __init__(self):
        """Initialize AWS pricing client."""
        if boto3 is None:
            raise AWSPricingError(
                "boto3 is required for AWS pricing. Install with: pip install boto3"
            )
        self.pricing_client = boto3.client('pricing', region_name=config.AWS_PRICING_REGION)
        self.cache_ttl = timedelta(seconds=config.PRICING_CACHE_TTL_SECONDS)
    
    def _get_cache_key(self, service_code: str, instance_type: str, region: str) -> str:
        """Generate cache key."""
        return f"{service_code}:{instance_type}:{region}"
    
    def _get_cached_price(self, cache_key: str) -> Optional[float]:
        """Get cached price if still valid."""
        if cache_key in self._cache:
            price, timestamp = self._cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return price
            # Expired, remove from cache
            del self._cache[cache_key]
        return None
    
    def _cache_price(self, cache_key: str, price: float) -> None:
        """Cache price with current timestamp."""
        self._cache[cache_key] = (price, datetime.now())
    
    def _normalize_region(self, region: str) -> str:
        """
        Normalize AWS region name for pricing API.
        Pricing API uses region codes like 'ap-south-1'.
        
        Args:
            region: AWS region code (e.g., 'ap-south-1')
        
        Returns:
            Normalized region name for pricing API
        """
        # AWS pricing API expects region codes as-is
        return region
    
    async def get_ec2_instance_price(
        self,
        instance_type: str,
        region: str,
        operating_system: str = "Linux"
    ) -> Optional[float]:
        """
        Get hourly price for EC2 instance.
        
        Args:
            instance_type: EC2 instance type (e.g., 't3.micro')
            region: AWS region (e.g., 'us-east-1')
            operating_system: OS type (default: 'Linux')
        
        Returns:
            Hourly price in USD, or None if not found
        
        Raises:
            AWSPricingError: If API call fails
        """
        cache_key = self._get_cache_key("AmazonEC2", instance_type, region)
        cached_price = self._get_cached_price(cache_key)
        if cached_price is not None:
            return cached_price
        
        try:
            # Normalize region for pricing API
            normalized_region = self._normalize_region(region)
            
            # Query pricing API
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': normalized_region},
                    {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': operating_system},
                    {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                    {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'Used'},
                ],
                MaxResults=1
            )
            
            # Parse price from response
            if response.get('PriceList'):
                import json
                price_data = json.loads(response['PriceList'][0])
                
                # Extract On-Demand price
                terms = price_data.get('terms', {}).get('OnDemand', {})
                if terms:
                    term_key = list(terms.keys())[0]
                    price_dimensions = terms[term_key].get('priceDimensions', {})
                    if price_dimensions:
                        dimension_key = list(price_dimensions.keys())[0]
                        price_per_unit = price_dimensions[dimension_key].get('pricePerUnit', {}).get('USD')
                        if price_per_unit:
                            hourly_price = float(price_per_unit)
                            self._cache_price(cache_key, hourly_price)
                            return hourly_price
            
            return None
        
        except ClientError as error:
            logger.error(f"AWS pricing API error: {error}")
            raise AWSPricingError(f"Failed to query AWS pricing: {str(error)}") from error
        except (BotoCoreError, ValueError, KeyError) as error:
            logger.error(f"Error parsing AWS pricing response: {error}")
            raise AWSPricingError(f"Failed to parse AWS pricing response: {str(error)}") from error
    
    async def get_rds_instance_price(
        self,
        instance_type: str,
        region: str,
        engine: str = "mysql"
    ) -> Optional[float]:
        """
        Get hourly price for RDS instance.
        
        Args:
            instance_type: RDS instance type (e.g., 'db.t3.micro')
            region: AWS region
            engine: Database engine (default: 'mysql')
        
        Returns:
            Hourly price in USD, or None if not found
        
        Raises:
            AWSPricingError: If API call fails
        """
        cache_key = self._get_cache_key("AmazonRDS", instance_type, region)
        cached_price = self._get_cached_price(cache_key)
        if cached_price is not None:
            return cached_price
        
        try:
            normalized_region = self._normalize_region(region)
            
            response = self.pricing_client.get_products(
                ServiceCode='AmazonRDS',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': normalized_region},
                    {'Type': 'TERM_MATCH', 'Field': 'databaseEngine', 'Value': engine},
                    {'Type': 'TERM_MATCH', 'Field': 'deploymentOption', 'Value': 'Single-AZ'},
                ],
                MaxResults=1
            )
            
            if response.get('PriceList'):
                import json
                price_data = json.loads(response['PriceList'][0])
                terms = price_data.get('terms', {}).get('OnDemand', {})
                if terms:
                    term_key = list(terms.keys())[0]
                    price_dimensions = terms[term_key].get('priceDimensions', {})
                    if price_dimensions:
                        dimension_key = list(price_dimensions.keys())[0]
                        price_per_unit = price_dimensions[dimension_key].get('pricePerUnit', {}).get('USD')
                        if price_per_unit:
                            hourly_price = float(price_per_unit)
                            self._cache_price(cache_key, hourly_price)
                            return hourly_price
            
            return None
        
        except (ClientError, BotoCoreError, ValueError, KeyError) as error:
            logger.error(f"Error querying RDS pricing: {error}")
            # Don't raise, return None to indicate pricing not found
            return None
