# AWS Pricing Architecture

## Overview

This document explains how AWS pricing is handled in the Terraform cost estimator. The system uses **AWS Price List Bulk API** for fast, reliable pricing lookups.

## Why Bulk API?

1. **Performance**: AWS pricing data is enormous (many services × regions × SKUs). A single JSON can be multi-GB.
2. **Reliability**: Pricing changes frequently (sometimes daily). Hardcoded data becomes stale fast.
3. **Scalability**: Bulk API is designed for high-throughput consumption of pricing data.

## Architecture

### 1. Data Sync (Node.js)

The `aws-pricing-sync.mjs` script downloads pricing data from AWS:

```bash
# Core services (recommended)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# All services, all regions (huge download)
node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8
```

**What it does:**
- Fetches service index: `https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json`
- For each service, fetches region index
- Downloads regional offer files (compressed `.json.gz`)
- Creates `manifest.json` with metadata

**Output structure:**
```
pricing-cache/aws/
  AmazonEC2/
    us-east-1.json.gz
    eu-west-1.json.gz
    ...
  AmazonRDS/
    us-east-1.json.gz
    ...
  manifest.json
```

### 2. Backend Client (Python)

The `AWSBulkPricingClient` reads from cached files:

```python
from backend.pricing.aws_bulk_pricing import AWSBulkPricingClient

client = AWSBulkPricingClient(cache_dir="pricing-cache/aws")
price = await client.get_ec2_instance_price("t3.micro", "us-east-1")
```

**Features:**
- O(1) lookups from pre-indexed data
- In-memory caching of loaded offer files
- Automatic hourly → monthly conversion (730 hours/month)
- Handles gzipped and uncompressed files

### 3. Fallback Strategy

The system uses a hybrid approach:

1. **Primary**: Bulk pricing client (if cache exists)
2. **Fallback**: boto3 `get_products` API (current implementation)

This ensures:
- Fast lookups when cache is available
- Still works if cache is missing (slower, but functional)

## Offer File Structure

AWS offer files have this structure:

```json
{
  "formatVersion": "v1.0",
  "publicationDate": "2024-01-15T00:00:00Z",
  "products": {
    "SKU123": {
      "attributes": {
        "instanceType": "t3.micro",
        "operatingSystem": "Linux",
        "location": "US East (N. Virginia)",
        ...
      }
    }
  },
  "terms": {
    "OnDemand": {
      "SKU123": {
        "TERM_CODE": {
          "priceDimensions": {
            "RATE_CODE": {
              "pricePerUnit": {
                "USD": "0.0104"
              },
              "unit": "Hrs"
            }
          }
        }
      }
    }
  }
}
```

## Price Calculation

### Units

AWS uses different units:
- **Hrs / Hours**: Compute instances (multiply by 730 for monthly)
- **GB-Mo**: Storage (already monthly)
- **Requests**: API calls
- **GB**: Data transfer

### Conversion

```python
# Hourly → Monthly
monthly_price = hourly_price * 730  # HOURS_PER_MONTH

# Storage (already monthly)
monthly_storage = gb_price * storage_gb

# Data transfer
monthly_transfer = gb_price * transfer_gb
```

## Usage in Cost Estimator

The cost estimator automatically uses bulk pricing when available:

```python
# In cost_estimator.py
from backend.pricing.aws_bulk_pricing import create_bulk_pricing_client

bulk_client = create_bulk_pricing_client()
if bulk_client:
    # Use fast bulk pricing
    price = await bulk_client.get_ec2_instance_price(instance_type, region)
else:
    # Fallback to API
    price = await aws_client.get_ec2_instance_price(instance_type, region)
```

## Maintenance

### Updating Pricing Data

Run sync script periodically (daily recommended):

```bash
# Add to cron or scheduled task
0 2 * * * cd /path/to/project && node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
```

### Monitoring

Check `manifest.json` for:
- `generatedAt`: When data was last synced
- `publicationDate`: AWS publication date (per service)
- `downloads`: List of downloaded files with sizes

## Performance

**Bulk pricing (cached):**
- Lookup: ~1-5ms (in-memory)
- Initial load: ~100-500ms per offer file (one-time)

**API pricing (boto3):**
- Lookup: ~200-1000ms (network + API call)
- Rate limits: 5 requests/second (AWS default)

**Recommendation**: Always use bulk pricing in production.

## Troubleshooting

### Cache not found
```
AWSBulkPricingError: Pricing cache directory not found
```
**Solution**: Run `aws-pricing-sync.mjs` to download data.

### Stale data
Check `manifest.json` → `generationDate`. If > 7 days old, re-sync.

### Missing service/region
Add service to sync command:
```bash
node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEC2,AmazonS3
```

## References

- [AWS Price List API Documentation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)
- [Bulk API Endpoints](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-ppslong.html)
