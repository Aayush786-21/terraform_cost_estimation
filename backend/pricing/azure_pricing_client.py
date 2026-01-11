"""
Azure Retail Prices API client.
Uses public REST API (no authentication required).
"""
from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta
import httpx

from backend.core.config import config
from backend.resilience.circuit_breaker import get_circuit_breaker


logger = logging.getLogger(__name__)


class AzurePricingError(Exception):
    """Raised when Azure pricing lookup fails."""
    pass


class AzurePricingClient:
    """Client for querying Azure Retail Prices API."""
    
    # In-memory cache: (arm_region, service_family, sku_name) -> (price, timestamp)
    _cache: Dict[str, tuple] = {}
    
    API_BASE_URL = "https://prices.azure.com/api/retail/prices"
    
    def __init__(self):
        """Initialize Azure pricing client."""
        self.cache_ttl = timedelta(seconds=config.PRICING_CACHE_TTL_SECONDS)
        self.timeout = 10.0  # 10 seconds timeout for Azure pricing API
        self.circuit_breaker = get_circuit_breaker("azure_pricing")
    
    def _get_cache_key(self, arm_region: str, service_family: str, sku_name: str) -> str:
        """Generate cache key."""
        return f"{arm_region}:{service_family}:{sku_name}"
    
    def _get_cached_price(self, cache_key: str) -> Optional[float]:
        """Get cached price if still valid."""
        if cache_key in self._cache:
            price, timestamp = self._cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return price
            del self._cache[cache_key]
        return None
    
    def _cache_price(self, cache_key: str, price: float) -> None:
        """Cache price with current timestamp."""
        self._cache[cache_key] = (price, datetime.now())
    
    def _normalize_region(self, region: str) -> str:
        """
        Normalize Azure region name for pricing API.
        Pricing API uses ARM region names like 'eastus'.
        
        Args:
            region: Azure region (e.g., 'eastus' or 'East US')
        
        Returns:
            Normalized region name (lowercase, no spaces)
        """
        # Remove spaces and convert to lowercase
        return region.lower().replace(" ", "")
    
    async def get_virtual_machine_price(
        self,
        sku_name: str,
        region: str,
        os_type: str = "Linux"
    ) -> Optional[float]:
        """
        Get hourly price for Azure Virtual Machine.
        
        Args:
            sku_name: VM SKU (e.g., 'Standard_B1s')
            region: Azure region (e.g., 'eastus')
            os_type: OS type ('Linux' or 'Windows')
        
        Returns:
            Hourly price in USD, or None if not found
        
        Raises:
            AzurePricingError: If API call fails
        """
        cache_key = self._get_cache_key(region, "Compute", sku_name)
        cached_price = self._get_cached_price(cache_key)
        if cached_price is not None:
            return cached_price
        
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            return None  # Fail silently, circuit breaker open
        
        try:
            normalized_region = self._normalize_region(region)
            
            # Query Azure Retail Prices API
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.API_BASE_URL,
                    params={
                        "$filter": f"armRegionName eq '{normalized_region}' "
                                 f"and serviceFamily eq 'Compute' "
                                 f"and skuName eq '{sku_name}' "
                                 f"and priceType eq 'Consumption' "
                                 f"and contains(productName, 'Virtual Machines')"
                    },
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                
                # Find Linux or Windows pricing
                items = data.get("Items", [])
                for item in items:
                    product_name = item.get("productName", "")
                    if os_type.lower() in product_name.lower():
                        unit_price = item.get("retailPrice")
                        if unit_price:
                            hourly_price = float(unit_price)
                            self._cache_price(cache_key, hourly_price)
                            self.circuit_breaker.record_success()
                            return hourly_price
                
                self.circuit_breaker.record_success()  # Not found is not a failure
                return None
        
        except httpx.HTTPStatusError as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Azure pricing API HTTP error: {error}")
            raise AzurePricingError(f"Failed to query Azure pricing: {error.response.status_code}") from error
        except httpx.RequestError as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Azure pricing API request error: {error}")
            raise AzurePricingError(f"Failed to connect to Azure pricing API: {str(error)}") from error
        except (ValueError, KeyError) as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Error parsing Azure pricing response: {error}")
            return None
        except Exception as error:
            self.circuit_breaker.record_failure()
            logger.error(f"Unexpected error in Azure pricing: {error}")
            raise AzurePricingError(f"Unexpected error in Azure pricing: {str(error)}") from error
