#!/bin/bash
# Start the backend server on port 8080
cd "$(dirname "$0")"
source venv/bin/activate
set -a
[ -f .env ] && source .env || echo 'No .env file, using current env'
set +a
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
