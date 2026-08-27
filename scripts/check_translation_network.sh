#!/bin/bash
# Network check script for translation retry trigger
# Writes status to a file that the retry cron job reads

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJECT/logs/.translation_network_state"
LOG_FILE="$PROJECT/logs/cron.log"
PYTHON="$PROJECT/backend/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="${PYTHON_BIN:-python3}"
fi
mkdir -p "$PROJECT/logs"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [net-check] $1" >> "$LOG_FILE"
}

cd "$PROJECT/backend"

# Run network check
if "$PYTHON" manage.py check_translation_network --json 2>/dev/null; then
    STATE="ok"
else
    STATE="down"
fi

# Read previous state
PREV_STATE=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")

# Write current state
echo "$STATE" > "$STATE_FILE"

log "Network check: current=$STATE, previous=$PREV_STATE"

# If network just recovered (was down, now ok), log and trigger retry
if [ "$PREV_STATE" = "down" ] && [ "$STATE" = "ok" ]; then
    log "NETWORK RECOVERED - triggering translation retry"
    echo "RECOVERED"
elif [ "$STATE" = "down" ]; then
    log "Network still down - skipping retry"
    echo "DOWN"
else
    echo "OK"
fi
