"""
AWS region code to Pricing API location string mapping.
AWS Pricing API uses human-readable location strings, not region codes.
"""
from typing import Dict, Optional, List


# AWS region code to Pricing API location string mapping
# Based on AWS Price List API location values
AWS_REGION_TO_LOCATION: Dict[str, str] = {
    # US East
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    
    # US West
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    
    # Asia Pacific
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    
    # Europe
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-central-2": "Europe (Zurich)",
    "eu-north-1": "Europe (Stockholm)",
    "eu-south-1": "Europe (Milan)",
    "eu-south-2": "Europe (Spain)",
    
    # Middle East
    "me-south-1": "Middle East (Bahrain)",
    "me-central-1": "Middle East (UAE)",
    
    # Africa
    "af-south-1": "Africa (Cape Town)",
    
    # South America
    "sa-east-1": "South America (Sao Paulo)",
    
    # Canada
    "ca-central-1": "Canada (Central)",
    
    # China
    "cn-north-1": "China (Beijing)",
    "cn-northwest-1": "China (Ningxia)",
}


def get_aws_pricing_location(region_code: str) -> Optional[str]:
    """
    Get AWS Pricing API location string from region code.
    
    Args:
        region_code: AWS region code (e.g., 'ap-south-1')
    
    Returns:
        Pricing API location string (e.g., 'Asia Pacific (Mumbai)'), or None if not found
    """
    return AWS_REGION_TO_LOCATION.get(region_code)


def get_all_aws_regions() -> list[str]:
    """
    Get all supported AWS region codes.
    
    Returns:
        List of AWS region codes
    """
    return list(AWS_REGION_TO_LOCATION.keys())
