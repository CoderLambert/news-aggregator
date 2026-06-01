#!/usr/bin/env bash
# fetch_full_content_cron.sh — safe entry point for cron / manual runs.
#
# Usage:
#   ./scripts/fetch_full_content_cron.sh        # normal run
#   FULL_CONTENT_FETCH_LIMIT=50 ./scripts/fetch_full_content_cron.sh
#   ./scripts/fetch_full_content_cron.sh dry-run
#
# Environment variables (defaults shown):
#   FULL_CONTENT_FETCH_LIMIT=20
#   FULL_CONTENT_MAX_RETRIES=3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"
LOG_DIR="${SCRIPT_DIR}/../logs"

cd "$BACKEND_DIR"
mkdir -p "$LOG_DIR"

# Simple network connectivity check
echo "[$(date -u +%FT%T)] Network check..."
if ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    # Fallback: try DNS resolution
    if ! python -c "import urllib.request; urllib.request.urlopen('https://www.google.com', timeout=5)" 2>/dev/null; then
        echo "[$(date -u +%FT%T)] WARNING: No network connectivity detected, skipping fetch." \
            | tee -a "$LOG_DIR/full_content_fetch.log"
        exit 0
    fi
fi

LIMIT="${FULL_CONTENT_FETCH_LIMIT:-20}"
MAX_RETRIES="${FULL_CONTENT_MAX_RETRIES:-3}"

MODE=""
if [[ "${1:-}" == "dry-run" ]]; then
    MODE="--dry-run"
fi

echo "[$(date -u +%FT%T)] Starting full_content_fetch (limit=${LIMIT}, max-retries=${MAX_RETRIES}, mode=${MODE:-normal})" \
    | tee -a "$LOG_DIR/full_content_fetch.log"

python manage.py fetch_full_content \
    --limit "$LIMIT" \
    --max-retries "$MAX_RETRIES" \
    $MODE \
    2>&1 | tee -a "$LOG_DIR/full_content_fetch.log"

EXIT_CODE=${PIPESTATUS[0]}

echo "[$(date -u +%FT%T)] Done (exit=${EXIT_CODE})" | tee -a "$LOG_DIR/full_content_fetch.log"
exit "$EXIT_CODE"
