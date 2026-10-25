#!/usr/bin/env bash
# Diagnostics only. Always succeed: monitoring must not mask a release failure.
set -u
CI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
printf 'NewsHub CI cache summary (no secrets or cache contents)\n'
timeout 8s bash "$CI_DIR/install-backend-deps.sh" --status 2>/dev/null \
    || printf 'backend cache status unavailable\n'
timeout 8s bash "$CI_DIR/install-frontend-deps.sh" --status 2>/dev/null \
    || printf 'frontend cache status unavailable\n'
if command -v docker >/dev/null 2>&1; then
    printf 'Docker build cache usage:\n'
    timeout 8s docker builder du 2>/dev/null | tail -n 4 || printf 'Docker cache usage unavailable\n'
fi
exit 0
