#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT/backend/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="${PYTHON_BIN:-python3}"
fi
mkdir -p "$PROJECT/logs"
cd "$PROJECT/backend"
"$PYTHON" manage.py crawl all >> "$PROJECT/logs/crawl.log" 2>&1
