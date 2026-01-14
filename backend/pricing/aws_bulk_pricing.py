"""
AWS Bulk Pricing Client.
Reads from locally cached AWS Price List Bulk API offer files.

This is the recommended approach for production:
- Fast: O(1) lookups from pre-indexed data
- Reliable: No API rate limits or network issues
- Up-to-date: Sync pricing data via aws-pricing-sync.mjs

Usage:
    # First, sync pricing data
    node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEC2,AmazonRDS

    # Then use in Python
    client = AWSBulkPricingClient(cache_dir="pricing-cache/aws")
    price = await client.get_ec2_instance_price("t3.micro", "us-east-1")
"""
import json
import gzip
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class AWSBulkPricingError(Exception):
    """Raised when bulk pricing lookup fails."""
    pass


class AWSBulkPricingClient:
    """
    Client for reading AWS pricing from cached bulk offer files.
    
    Expects directory structure:
        pricing-cache/aws/
            AmazonEC2/
                us-east-1.json.gz
                eu-west-1.json.gz
                ...
            AmazonRDS/
                ...
    """
    
    # Hours per month constant (for hourly -> monthly conversion)
    HOURS_PER_MONTH = 730.0
    
    def __init__(self, cache_dir: str = "pricing-cache/aws", prewarm_common_regions: bool = True):
        """
        Initialize bulk pricing client.
        
        Args:
            cache_dir: Path to pricing cache directory
            prewarm_common_regions: If True, pre-index common regions (us-east-1, us-west-2, eu-west-1)
                                    for faster first lookups. Default: True
        """
        self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            raise AWSBulkPricingError(
                f"Pricing cache directory not found: {cache_dir}. "
                f"Run: node aws-pricing-sync.mjs --out {cache_dir}"
            )
        
        # In-memory cache of loaded offer files: (service, region) -> offer_data
        self._offer_cache: Dict[tuple, Dict[str, Any]] = {}
        
        # Fast price lookup index: (service, region, lookup_key) -> price
        # lookup_key format: "instanceType:os:tenancy" or "instanceType:engine:deployment"
        # This provides O(1) lookups after initial indexing
        self._price_index: Dict[tuple, float] = {}
        
        # Index of product SKUs: (service, region, lookup_key) -> sku
        # Allows fast SKU lookup without searching all products
        self._sku_index: Dict[tuple, str] = {}
        
        # Track which regions have been indexed
        self._indexed_regions: set = set()
        
        # Pre-warm common regions for faster lookups
        if prewarm_common_regions:
            self._prewarm_common_regions()
    
    def _load_offer_file(self, service_code: str, region_code: str) -> Optional[Dict[str, Any]]:
        """
        Load and parse an offer file for a service/region.
        
        Args:
            service_code: AWS service code (e.g., 'AmazonEC2')
            region_code: AWS region code (e.g., 'us-east-1')
        
        Returns:
            Parsed offer file data, or None if not found
        """
        cache_key = (service_code, region_code)
        
        # Check in-memory cache
        if cache_key in self._offer_cache:
            return self._offer_cache[cache_key]
        
        # Try gzipped file first
        json_path = self.cache_dir / service_code / f"{region_code}.json.gz"
        if not json_path.exists():
            # Try uncompressed
            json_path = self.cache_dir / service_code / f"{region_code}.json"
            if not json_path.exists():
                logger.warning(f"Offer file not found: {json_path}")
                return None
        
        try:
            # Read and parse JSON
            if json_path.suffix == ".gz":
                with gzip.open(json_path, "rt", encoding="utf-8") as f:
                    offer_data = json.load(f)
            else:
                with open(json_path, "r", encoding="utf-8") as f:
                    offer_data = json.load(f)
            
            # Cache in memory
            self._offer_cache[cache_key] = offer_data
            return offer_data
            
        except (json.JSONDecodeError, IOError, gzip.BadGzipFile) as e:
            logger.error(f"Error loading offer file {json_path}: {e}")
            return None
    
    def _build_lookup_key(self, filters: Dict[str, str]) -> str:
        """
        Build a lookup key from filters for indexing.
        
        Args:
            filters: Dict of attribute filters
        
        Returns:
            Lookup key string (e.g., "t3.micro:Linux:Shared")
        """
        # Normalize and sort for consistent keys
        parts = []
        for key in sorted(filters.keys()):
            value = filters[key]
            # Normalize values for consistent lookup
            if key.lower() in ["databaseengine", "operatingsystem"]:
                value = value.lower()
            parts.append(f"{key}:{value}")
        return "|".join(parts)
    
    def _index_offer_file(self, service_code: str, region_code: str, offer_data: Dict[str, Any]) -> None:
        """
        Build fast lookup index for an offer file.
        
        This pre-indexes common lookup patterns for O(1) price retrieval.
        
        Args:
            service_code: AWS service code
            region_code: AWS region code
            offer_data: Parsed offer file JSON
        """
        cache_key = (service_code, region_code)
        if cache_key in self._indexed_regions:
            return  # Already indexed
        
        products = offer_data.get("products", {})
        terms = offer_data.get("terms", {}).get("OnDemand", {})
        
        indexed_count = 0
        
        for sku, product in products.items():
            attributes = product.get("attributes", {})
            
            # Index EC2 instances
            if service_code == "AmazonEC2":
                instance_type = attributes.get("instanceType", "")
                os = attributes.get("operatingSystem", "")
                tenancy = attributes.get("tenancy", "")
                capacity = attributes.get("capacitystatus", "")
                preinstalled = attributes.get("preInstalledSw", "")
                
                if instance_type and os and tenancy:
                    # Build lookup key WITHOUT capacitystatus (matches our filter)
                    lookup_key = self._build_lookup_key({
                        "instanceType": instance_type,
                        "operatingSystem": os,
                        "tenancy": tenancy
                    })
                    
                    # Extract price
                    if sku in terms:
                        term_entries = terms[sku]
                        term_code = list(term_entries.keys())[0]
                        price_dimensions = term_entries[term_code].get("priceDimensions", {})
                        if price_dimensions:
                            dimension_code = list(price_dimensions.keys())[0]
                            price_per_unit = price_dimensions[dimension_code].get("pricePerUnit", {}).get("USD")
                            if price_per_unit:
                                index_key = (service_code, region_code, lookup_key)
                                price = float(price_per_unit)

                                # Only index standard images without pre-installed software (e.g. SQL Web)
                                # This avoids accidentally picking more expensive "Linux with SQL" SKUs
                                # when the caller just asks for generic Linux pricing.
                                is_plain_image = preinstalled in ("NA", "", None)
                                
                                # Prefer "Used" capacity over reservations, but only for plain images
                                # Only store if not already indexed, or if replacing a reservation with "Used"
                                if is_plain_image:
                                    if index_key in self._price_index:
                                        # Check if existing is a reservation
                                        existing_sku = self._sku_index.get(index_key)
                                        if existing_sku:
                                            existing_product = products.get(existing_sku, {})
                                            existing_capacity = existing_product.get("attributes", {}).get("capacitystatus", "").lower()
                                            # Replace reservation with standard "Used" pricing
                                            if existing_capacity != "used" and capacity.lower() == "used":
                                                self._price_index[index_key] = price
                                                self._sku_index[index_key] = sku
                                    else:
                                        # First time seeing this key - only index if it's "Used" capacity
                                        if capacity.lower() == "used":
                                            self._price_index[index_key] = price
                                            self._sku_index[index_key] = sku
                                            indexed_count += 1
            
            # Index RDS instances
            elif service_code == "AmazonRDS":
                instance_type = attributes.get("instanceType", "")
                engine = attributes.get("databaseEngine", "")
                deployment = attributes.get("deploymentOption", "")
                
                if instance_type and engine and deployment:
                    lookup_key = self._build_lookup_key({
                        "instanceType": instance_type,
                        "databaseEngine": engine,
                        "deploymentOption": deployment
                    })
                    
                    # Extract price
                    if sku in terms:
                        term_entries = terms[sku]
                        term_code = list(term_entries.keys())[0]
                        price_dimensions = term_entries[term_code].get("priceDimensions", {})
                        if price_dimensions:
                            dimension_code = list(price_dimensions.keys())[0]
                            price_per_unit = price_dimensions[dimension_code].get("pricePerUnit", {}).get("USD")
                            if price_per_unit:
                                index_key = (service_code, region_code, lookup_key)
                                self._price_index[index_key] = float(price_per_unit)
                                self._sku_index[index_key] = sku
                                indexed_count += 1
        
        if indexed_count > 0:
            self._indexed_regions.add(cache_key)
            logger.debug(f"Indexed {indexed_count} prices for {service_code}/{region_code}")
    
    def _extract_price_from_offer(
        self,
        service_code: str,
        region_code: str,
        offer_data: Dict[str, Any],
        filters: Dict[str, str]
    ) -> Optional[float]:
        """
        Extract price from offer file data based on filters.
        Uses pre-built index for fast lookups when available.
        
        Args:
            service_code: AWS service code
            region_code: AWS region code
            offer_data: Parsed offer file JSON
            filters: Dict of attribute filters (e.g., {'instanceType': 't3.micro'})
        
        Returns:
            Hourly price in USD, or None if not found
        """
        # Try fast index lookup first
        lookup_key = self._build_lookup_key(filters)
        index_key = (service_code, region_code, lookup_key)
        
        if index_key in self._price_index:
            return self._price_index[index_key]
        
        # Index not available, build it now (lazy indexing)
        self._index_offer_file(service_code, region_code, offer_data)
        
        # Try index again after building
        if index_key in self._price_index:
            return self._price_index[index_key]
        
        # Fallback to linear search (shouldn't happen often after indexing)
        products = offer_data.get("products", {})
        terms = offer_data.get("terms", {}).get("OnDemand", {})
        
        # Find ALL matching product SKUs (there may be multiple)
        matching_skus = []
        for sku, product in products.items():
            attributes = product.get("attributes", {})
            
            # Check if all filters match
            matches = True
            for key, value in filters.items():
                # Normalize attribute keys (AWS uses camelCase)
                attr_key = self._normalize_attribute_key(key)
                attr_value = attributes.get(attr_key, "")
                
                # Case-insensitive comparison for databaseEngine and some other fields
                if key.lower() in ["databaseengine", "operatingsystem", "enginename"]:
                    if attr_value.lower() != value.lower():
                        matches = False
                        break
                else:
                    if attr_value != value:
                        matches = False
                        break
            
            if matches:
                # Get capacity status to filter out reservations
                capacity_status = attributes.get("capacitystatus", "").lower()
                matching_skus.append((sku, capacity_status))
        
        if not matching_skus:
            return None
        
        # Prefer standard "Used" capacity over reservations
        # Filter priority: Used > UnusedCapacityReservation > AllocatedCapacityReservation
        def sku_priority(sku_info):
            _, capacity = sku_info
            if capacity == "used":
                return 0  # Best
            elif "unused" in capacity:
                return 1
            elif "allocated" in capacity:
                return 2
            else:
                return 3  # Unknown
        
        matching_skus.sort(key=sku_priority)
        
        # Helper to compute the lowest OnDemand hourly price for a set of SKUs
        def find_lowest_price(candidates):
            best_price = None
            best_sku = None
            
            for sku, _capacity in candidates:
                if sku not in terms:
                    continue
                
                term_entries = terms[sku]
                for term_code, term_data in term_entries.items():
                    price_dimensions = term_data.get("priceDimensions", {})
                    if not price_dimensions:
                        continue
                    
                    for dim in price_dimensions.values():
                        price_per_unit = dim.get("pricePerUnit", {}).get("USD")
                        if not price_per_unit:
                            continue
                        try:
                            price = float(price_per_unit)
                        except (TypeError, ValueError):
                            continue
                        
                        if best_price is None or price < best_price:
                            best_price = price
                            best_sku = sku
            
            return best_price, best_sku
        
        # First, try to find the lowest price among "Used" capacity SKUs
        used_skus = [s for s in matching_skus if s[1] == "used"]
        price, best_sku = find_lowest_price(used_skus if used_skus else matching_skus)
        
        if price is None:
            return None
        
        # Cache only when we have a concrete best SKU
        if best_sku is not None:
            self._price_index[index_key] = price
            self._sku_index[index_key] = best_sku
        
        return price
    
    def _prewarm_common_regions(self) -> None:
        """
        Pre-index common regions (us-east-1, us-west-2, eu-west-1) for faster lookups.
        This is called during initialization to reduce latency for first requests.
        """
        common_regions = ["us-east-1", "us-west-2", "eu-west-1"]
        common_services = ["AmazonEC2", "AmazonRDS"]
        
        indexed_count = 0
        for service in common_services:
            for region in common_regions:
                try:
                    offer_data = self._load_offer_file(service, region)
                    if offer_data:
                        before = len(self._price_index)
                        self._index_offer_file(service, region, offer_data)
                        after = len(self._price_index)
                        indexed_count += (after - before)
                except Exception as e:
                    # Skip corrupted files, log warning
                    logger.debug(f"Skipping pre-warm for {service}/{region}: {e}")
                    continue
        
        if indexed_count > 0:
            logger.info(f"Pre-warmed pricing index: {indexed_count} prices cached")
    
    def _normalize_attribute_key(self, key: str) -> str:
        """
        Normalize filter key to AWS attribute key format.
        
        AWS uses camelCase in offer files (e.g., 'instanceType', 'operatingSystem').
        """
        key_map = {
            "instance_type": "instanceType",
            "operating_system": "operatingSystem",
            "database_engine": "databaseEngine",
            "deployment_option": "deploymentOption",
        }
        return key_map.get(key.lower(), key)
    
    async def get_ec2_instance_price(
        self,
        instance_type: str,
        region: str,
        operating_system: str = "Linux"
    ) -> Optional[float]:
        """
        Get hourly price for EC2 instance from cached offer files.
        
        Args:
            instance_type: EC2 instance type (e.g., 't3.micro')
            region: AWS region (e.g., 'us-east-1')
            operating_system: OS type (default: 'Linux')
        
        Returns:
            Hourly price in USD, or None if not found
        """
        offer_data = self._load_offer_file("AmazonEC2", region)
        if not offer_data:
            return None
        
        filters = {
            "instanceType": instance_type,
            "operatingSystem": operating_system,
            "tenancy": "Shared",
            "capacitystatus": "Used",
        }
        
        return self._extract_price_from_offer("AmazonEC2", region, offer_data, filters)
    
    async def get_rds_instance_price(
        self,
        instance_type: str,
        region: str,
        engine: str = "mysql"
    ) -> Optional[float]:
        """
        Get hourly price for RDS instance from cached offer files.
        
        Args:
            instance_type: RDS instance type (e.g., 'db.t3.micro')
            region: AWS region
            engine: Database engine (default: 'mysql')
        
        Returns:
            Hourly price in USD, or None if not found
        """
        offer_data = self._load_offer_file("AmazonRDS", region)
        if not offer_data:
            return None
        
        # Normalize engine name (MySQL, MariaDB, PostgreSQL, etc.)
        engine_map = {
            "mysql": "MySQL",
            "mariadb": "MariaDB",
            "postgres": "PostgreSQL",
            "postgresql": "PostgreSQL",
            "sqlserver": "SQL Server",
            "oracle": "Oracle"
        }
        normalized_engine = engine_map.get(engine.lower(), engine)
        
        filters = {
            "instanceType": instance_type,
            "databaseEngine": normalized_engine,
            "deploymentOption": "Single-AZ",
        }
        
        return self._extract_price_from_offer("AmazonRDS", region, offer_data, filters)
    
    def hourly_to_monthly(self, hourly_price: float) -> float:
        """
        Convert hourly price to monthly price.
        
        Uses standard 730 hours per month.
        
        Args:
            hourly_price: Hourly price in USD
        
        Returns:
            Monthly price in USD
        """
        return hourly_price * self.HOURS_PER_MONTH
    
    def get_offer_publication_date(self, service_code: str, region_code: str) -> Optional[str]:
        """
        Get publication date of offer file (from manifest or offer file itself).
        
        Args:
            service_code: AWS service code
            region_code: AWS region code
        
        Returns:
            ISO date string, or None if not found
        """
        offer_data = self._load_offer_file(service_code, region_code)
        if not offer_data:
            return None
        
        # Offer files have publicationDate at root
        return offer_data.get("publicationDate")


# Factory function for easy instantiation
def create_bulk_pricing_client(cache_dir: Optional[str] = None) -> Optional[AWSBulkPricingClient]:
    """
    Create bulk pricing client if cache directory exists.
    
    Args:
        cache_dir: Optional path to cache directory (default: "pricing-cache/aws")
    
    Returns:
        AWSBulkPricingClient instance, or None if cache not found
    """
    if cache_dir is None:
        cache_dir = "pricing-cache/aws"
    
    try:
        return AWSBulkPricingClient(cache_dir=cache_dir)
    except AWSBulkPricingError:
        logger.debug(f"Bulk pricing cache not available at {cache_dir}")
        return None
