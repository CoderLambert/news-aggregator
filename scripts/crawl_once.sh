#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$PROJECT/logs/crawler.lock"
SPIDER="${1:-all}"

mkdir -p "$PROJECT/logs"

PYTHON="$PROJECT/backend/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="${PYTHON_BIN:-python3}"
fi

if ! command -v flock >/dev/null 2>&1; then
  echo "flock is required to prevent overlapping crawls." >&2
  exit 1
fi

cd "$PROJECT/backend"
flock -n -E 75 "$LOCK_FILE" \
  env NEWS_CRAWL_ONLY=1 PYTHONUNBUFFERED=1 \
  "$PYTHON" manage.py crawl "$SPIDER"
result=$?

if [ "$result" -eq 75 ]; then
  echo "A crawler already holds the project lock; this run was skipped."
  exit 0
fi
exit "$result"
