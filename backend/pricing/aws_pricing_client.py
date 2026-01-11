"""
AWS Pricing API client.
Uses boto3 to query official AWS Price List API.
"""
from typing import Dict, Any, Optional, Tuple
import logging
import hashlib
from datetime import datetime, timedelta

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    from botocore.config import Config
except ImportError:
    boto3 = None
    Config = None

from backend.core.config import config
from backend.pricing.aws_region_map import get_aws_pricing_location
from backend.resilience.circuit_breaker import get_circuit_breaker


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
        # Configure timeout: 10 seconds for pricing API calls
        boto_config = Config(
            connect_timeout=10,
            read_timeout=10,
            retries={'max_attempts': 0}  # No retries, circuit breaker handles failures
        )
        self.pricing_client = boto3.client(
            'pricing',
            region_name=config.AWS_PRICING_REGION,
            config=boto_config
        )
        self.cache_ttl = timedelta(seconds=config.PRICING_CACHE_TTL_SECONDS)
        self.circuit_breaker = get_circuit_breaker("aws_pricing")
    
    def _get_cache_key(
        self, 
        service_code: str, 
        instance_type: str, 
        region: str,
        filters_hash: str = ""
    ) -> str:
        """
        Generate cache key.
        
        Args:
            service_code: AWS service code (e.g., 'AmazonEC2')
            instance_type: Instance type (e.g., 't3.micro')
            region: Region code (e.g., 'ap-south-1')
            filters_hash: Optional hash of filter parameters to avoid cache collisions
        """
        base_key = f"{service_code}:{instance_type}:{region}"
        if filters_hash:
            return f"{base_key}:{filters_hash}"
        return base_key
    
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
    
    def _normalize_region(self, region_code: str) -> Tuple[str, Optional[str]]:
        """
        Normalize AWS region code for pricing API.
        AWS Pricing API uses human-readable location strings, not region codes.
        
        Args:
            region_code: AWS region code (e.g., 'ap-south-1')
        
        Returns:
            Tuple of (region_code, pricing_location_string)
            pricing_location_string is None if region code not found
        """
        pricing_location = get_aws_pricing_location(region_code)
        return region_code, pricing_location
    
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
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            raise AWSPricingError(
                "AWS pricing service temporarily unavailable (circuit breaker open)"
            )
        
        try:
            # Normalize region for pricing API
            region_code, pricing_location = self._normalize_region(region)
            
            if pricing_location is None:
                logger.warning(f"AWS region code '{region}' not found in region map")
                self.circuit_breaker.record_success()  # Not found is not a failure
                return None
            
            # Build filter hash for cache key (includes OS, tenancy, capacity status)
            filter_params = f"{operating_system}:Shared:Used"
            filters_hash = hashlib.md5(filter_params.encode()).hexdigest()[:8]
            cache_key_with_filters = self._get_cache_key("AmazonEC2", instance_type, region, filters_hash)
            
            cached_price = self._get_cached_price(cache_key_with_filters)
            if cached_price is not None:
                return cached_price
            
            # Query pricing API using location string (not region code)
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': pricing_location},  # Use location string
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
                            self._cache_price(cache_key_with_filters, hourly_price)
                            self.circuit_breaker.record_success()
                            return hourly_price
            
            self.circuit_breaker.record_success()  # Not found is not a failure
            return None

        except ClientError as error:
            self.circuit_breaker.record_failure()
            logger.error(f"AWS pricing API error: {error}")
            raise AWSPricingError(f"Failed to query AWS pricing: {str(error)}") from error
        except (BotoCoreError, ValueError, KeyError) as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Error parsing AWS pricing response: {error}")
            raise AWSPricingError(f"Failed to parse AWS pricing response: {str(error)}") from error
        except Exception as error:
            self.circuit_breaker.record_failure()
            raise AWSPricingError(f"Unexpected error querying AWS pricing: {str(error)}") from error
    
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
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            return None  # Fail silently, circuit breaker open
        
        try:
            # Normalize region for pricing API
            region_code, pricing_location = self._normalize_region(region)
            
            if pricing_location is None:
                logger.warning(f"AWS region code '{region}' not found in region map")
                self.circuit_breaker.record_success()  # Not found is not a failure
                return None
            
            # Build filter hash for cache key
            filter_params = f"{engine}:Single-AZ"
            filters_hash = hashlib.md5(filter_params.encode()).hexdigest()[:8]
            cache_key_with_filters = self._get_cache_key("AmazonRDS", instance_type, region, filters_hash)
            
            cached_price = self._get_cached_price(cache_key_with_filters)
            if cached_price is not None:
                return cached_price
            
            response = self.pricing_client.get_products(
                ServiceCode='AmazonRDS',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': pricing_location},  # Use location string
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
                            self._cache_price(cache_key_with_filters, hourly_price)
                            self.circuit_breaker.record_success()
                            return hourly_price
            
            self.circuit_breaker.record_success()  # Not found is not a failure
            return None

        except (ClientError, BotoCoreError, ValueError, KeyError) as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Error querying RDS pricing: {error}")
            # Don't raise, return None to indicate pricing not found
            return None
        except Exception as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Unexpected error querying RDS pricing: {error}")
            return None
