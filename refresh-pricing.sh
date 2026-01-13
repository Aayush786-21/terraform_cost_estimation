#!/bin/bash
# Refresh AWS pricing cache
# Run this daily to keep pricing data up-to-date
# Usage: ./refresh-pricing.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "AWS Pricing Cache Refresh"
echo "Started at: $(date)"
echo "=========================================="

# Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed or not in PATH"
    echo "Please install Node.js (v18 or later) to run the sync script"
    exit 1
fi

# Check if sync script exists
if [ ! -f "aws-pricing-sync.mjs" ]; then
    echo "Error: aws-pricing-sync.mjs not found in current directory"
    exit 1
fi

# Run the sync script
echo "Running pricing sync..."
node aws-pricing-sync.mjs --out pricing-cache/aws --gzip

SYNC_EXIT_CODE=$?

if [ $SYNC_EXIT_CODE -eq 0 ]; then
    echo "=========================================="
    echo "Pricing sync completed successfully!"
    echo "Finished at: $(date)"
    echo "=========================================="
    
    # Show summary
    if [ -f "pricing-cache/manifest.json" ]; then
        echo ""
        echo "Cache summary:"
        echo "  Services: $(find pricing-cache/aws -mindepth 1 -maxdepth 1 -type d | wc -l)"
        echo "  Total files: $(find pricing-cache/aws -name "*.json.gz" -o -name "*.json" | wc -l)"
        echo "  Cache size: $(du -sh pricing-cache/aws | cut -f1)"
        echo ""
    fi
else
    echo "=========================================="
    echo "Pricing sync failed with exit code: $SYNC_EXIT_CODE"
    echo "You can resume later - already downloaded files will be skipped"
    echo "=========================================="
    exit $SYNC_EXIT_CODE
fi
