# Setting Up AWS Pricing Cache

## Quick Reference

```bash
# Start download (core services, ~10-30 min)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# Resume if interrupted (skips existing files)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# Daily refresh
./refresh-pricing.sh

# Check if backend is using cache
# Look for "Using AWS bulk pricing client" in backend logs
```

## Overview

The AWS pricing cache downloads official pricing data from AWS Price List Bulk API. This enables fast, reliable pricing lookups without hitting API rate limits.

**⚠️ Important**: The initial download can take **30-60 minutes** or more depending on:
- Number of services selected
- Number of regions
- Your internet connection speed
- AWS server response times

**✅ Good News**: You can stop and resume anytime - the script automatically skips files that already exist!

## Getting Started Checklist

- [ ] Ensure Node.js v18+ is installed (`node --version`)
- [ ] Run initial sync (start with core services)
- [ ] Wait for download to complete (or resume later)
- [ ] Verify cache was created (`ls pricing-cache/aws/`)
- [ ] Start backend - it will automatically detect and use cache
- [ ] Check backend logs for "Using AWS bulk pricing client"
- [ ] Test with a cost estimate - should be fast!

## Quick Start

### Step 1: Run the Sync Script

```bash
# Core services only (recommended for first run - faster)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# Or all services (takes much longer, but complete)
node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8
```

### Step 2: What to Expect

The script will:
1. Fetch the service index (~1-2 seconds)
2. For each service, fetch region index (~1-2 seconds per service)
3. Download regional offer files (this is the slow part)
   - Each file can be 10-100MB+ uncompressed
   - With gzip, typically 2-20MB per file
   - Progress is shown as: `✓ AmazonEC2/us-east-1 (1234567 bytes raw)`

**Estimated download sizes:**
- Core services (EC2, RDS, S3, Lambda, etc.): ~500MB-2GB compressed
- All services: ~5-20GB compressed

### Step 3: Verify It Worked

After completion, check:

```bash
# Check manifest was created
ls -lh pricing-cache/manifest.json

# Check service directories exist
ls pricing-cache/aws/

# Check a sample file
ls -lh pricing-cache/aws/AmazonEC2/

# View manifest summary
cat pricing-cache/manifest.json | jq '.services | length'  # Number of services
cat pricing-cache/manifest.json | jq '.generatedAt'        # When synced
```

## Resuming Interrupted Downloads

**Good news**: The script automatically skips files that already exist!

If the download is interrupted:
1. Simply run the same command again
2. Already-downloaded files will be skipped (you'll see `skipped: true` in output)
3. Only missing files will be downloaded

**Example:**
```bash
# First run (interrupted after 10 minutes)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
# ... downloads 50 files, then you Ctrl+C

# Resume later (continues from where it left off)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
# ... skips 50 existing files, downloads remaining ones
```

## Forcing Re-download

If you want to re-download everything (e.g., pricing data is stale):

```bash
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip --force
```

## Recommended Approach

### Option 1: Start Small (Recommended)

Download core services first to get started quickly:

```bash
node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEC2,AmazonRDS,AmazonS3 --gzip
```

This downloads:
- EC2 (compute instances)
- RDS (databases)
- S3 (storage)

**Time estimate**: 5-15 minutes

Then add more services later as needed:
```bash
node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEBS,AWSLambda --gzip
```

### Option 2: Full Download (Overnight)

If you want everything upfront, run it overnight:

```bash
# Run in background, log output
nohup node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8 > pricing-sync.log 2>&1 &

# Check progress
tail -f pricing-sync.log

# Check if still running
ps aux | grep aws-pricing-sync
```

## Local Refresh Script

For keeping pricing data fresh, create a simple refresh script:

**`refresh-pricing.sh`**:
```bash
#!/bin/bash
# Refresh AWS pricing cache
# Run this daily to keep pricing data up-to-date

cd "$(dirname "$0")"
echo "Starting AWS pricing sync at $(date)"
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
echo "Pricing sync completed at $(date)"
```

Make it executable:
```bash
chmod +x refresh-pricing.sh
```

Run manually:
```bash
./refresh-pricing.sh
```

## Monitoring Progress

While the script runs, you can monitor:

```bash
# Watch file count grow
watch -n 5 'find pricing-cache/aws -name "*.json.gz" | wc -l'

# Watch disk usage
watch -n 5 'du -sh pricing-cache/aws'

# Check latest downloads
tail -f pricing-sync.log  # if using nohup
```

## Troubleshooting

### Script hangs or times out
- AWS servers can be slow. This is normal.
- Try reducing concurrency: `--concurrency 4`
- Check your internet connection

### Out of disk space
- Check available space: `df -h`
- Pricing cache can use 5-20GB+ for all services
- Consider downloading only needed services

### Network errors
- AWS servers occasionally have issues
- Script will retry on next run (skips completed files)
- Check AWS status page if persistent

### "Unexpected service index format"
- AWS may have changed their API format
- Check if script needs updating
- File an issue if this happens

## After Download Completes

Once the cache is ready:

1. **Backend automatically detects it**: No configuration needed!
   - The backend checks for `pricing-cache/aws/` on startup
   - If found, uses bulk pricing client automatically
   - Falls back to API client if cache not found

2. **Verify backend is using cache**:
   ```bash
   # Start backend and check logs
   # Look for this message:
   # "INFO: Using AWS bulk pricing client (cached offer files)"
   ```

3. **Test it**: Run a cost estimate - should be much faster now
   - Bulk pricing: ~1-5ms per lookup
   - API pricing: ~200-1000ms per lookup

4. **Check cache status**:
   ```python
   # In Python shell or backend code
   from backend.pricing.aws_bulk_pricing import create_bulk_pricing_client
   client = create_bulk_pricing_client()
   if client:
       print("✅ Bulk pricing cache is available!")
   else:
       print("❌ Bulk pricing cache not found")
   ```

## Maintenance

**Refresh frequency**: Daily recommended (pricing can change daily)

**Storage**: 
- Core services: ~500MB-2GB
- All services: ~5-20GB
- Plan disk space accordingly

**Cleanup old data**:
```bash
# Remove old cache if needed
rm -rf pricing-cache/aws
# Then re-sync
```

## Next Steps

Once pricing cache is ready:
1. ✅ Backend will automatically use it (no config needed)
2. ✅ Pricing lookups will be fast (~1-5ms vs ~200-1000ms)
3. ✅ No API rate limits to worry about
4. ✅ Works offline (after initial download)

## Command Reference

```bash
# Core services (fast, recommended first)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# Specific services
node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEC2,AmazonRDS --gzip

# All services (slow, complete)
node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8

# Specific regions only
node aws-pricing-sync.mjs --out pricing-cache/aws --regions us-east-1,eu-west-1 --gzip

# Force re-download
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip --force

# Uncompressed (not recommended - much larger)
node aws-pricing-sync.mjs --out pricing-cache/aws --no-gzip
```

## Time Estimates

| Scope | Services | Regions | Estimated Time | Size |
|-------|----------|---------|----------------|------|
| Core | 8 | All | 10-30 min | 500MB-2GB |
| Common | 15 | All | 20-45 min | 1-3GB |
| All | 100+ | All | 1-3 hours | 5-20GB |

*Times vary based on network speed and AWS server response times*

## Common Scenarios

### Scenario 1: First Time Setup
```bash
# 1. Start with core services (fastest way to get started)
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

# 2. Wait for completion (or resume later if interrupted)
# 3. Start your backend - it will automatically use the cache
# 4. Test with a Terraform estimate
```

### Scenario 2: Resume After Interruption
```bash
# Just run the same command - it skips existing files
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
```

### Scenario 3: Add More Services Later
```bash
# Already have EC2, RDS, S3? Add more:
node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEBS,AWSLambda,ElasticLoadBalancing --gzip
```

### Scenario 4: Full Download (Overnight)
```bash
# Start in background
nohup node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8 > pricing-sync.log 2>&1 &

# Check progress anytime
tail -f pricing-sync.log
```

### Scenario 5: Daily Refresh
```bash
# Use the refresh script
./refresh-pricing.sh

# Or manually
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip
```

## FAQ

**Q: Do I need to configure the backend to use the cache?**  
A: No! The backend automatically detects `pricing-cache/aws/` and uses it if available.

**Q: What if the download fails partway through?**  
A: Just run the same command again. The script skips files that already exist.

**Q: How often should I refresh the cache?**  
A: Daily is recommended. AWS pricing can change daily.

**Q: Can I use both bulk cache and API client?**  
A: The backend uses bulk cache if available, falls back to API client if not. You don't need both.

**Q: What if I run out of disk space?**  
A: Download only the services you need, or clean up old cache and re-sync specific services.

**Q: How do I know if the backend is using the cache?**  
A: Check backend logs for "Using AWS bulk pricing client (cached offer files)".

**Q: Can I share the cache between multiple backends?**  
A: Yes! Point multiple backends to the same `pricing-cache/aws/` directory.

## Summary

✅ **Download**: `node aws-pricing-sync.mjs --out pricing-cache/aws --gzip`  
✅ **Resume**: Same command (skips existing files)  
✅ **Refresh**: `./refresh-pricing.sh` or same download command  
✅ **Auto-detect**: Backend automatically uses cache when available  
✅ **Fast**: ~1-5ms lookups vs ~200-1000ms with API

The pricing cache is now ready to use! 🚀
