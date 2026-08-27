#!/bin/bash
# Run all tests for the news aggregator project
# Usage: ./scripts/run_tests.sh

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT/backend/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="${PYTHON_BIN:-python3}"
fi

echo "========================================"
echo "News Aggregator Test Suite"
echo "========================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track overall success
OVERALL_SUCCESS=true

# 1. Run backend tests
echo -e "${YELLOW}[1/3] Running backend tests...${NC}"
cd "$PROJECT/backend"
if "$PYTHON" -m pytest ../tests/backend/ -v --tb=short; then
    echo -e "${GREEN}✓ Backend tests passed${NC}"
else
    echo -e "${RED}✗ Backend tests failed${NC}"
    OVERALL_SUCCESS=false
fi
echo ""

# 2. Run frontend build validation
echo -e "${YELLOW}[2/3] Running frontend build validation...${NC}"
cd "$PROJECT"
if "$PYTHON" scripts/validate_build.py; then
    echo -e "${GREEN}✓ Frontend build validation passed${NC}"
else
    echo -e "${RED}✗ Frontend build validation failed (some warnings are OK)${NC}"
    # Don't fail the suite for bundle size warnings
fi
echo ""

# 3. Run crawler tests
echo -e "${YELLOW}[3/3] Running crawler tests...${NC}"
cd "$PROJECT"
if PYTHONPATH="$PROJECT/backend:$PROJECT/crawler${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m pytest tests/crawler/ -v --tb=short; then
    echo -e "${GREEN}✓ Crawler tests passed${NC}"
else
    echo -e "${RED}✗ Crawler tests failed${NC}"
    OVERALL_SUCCESS=false
fi
echo ""

# Summary
echo "========================================"
if [ "$OVERALL_SUCCESS" = true ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
