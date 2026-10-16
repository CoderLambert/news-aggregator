#!/usr/bin/env bash
# Diagnostics only. Always succeed: monitoring must not mask a release failure.
set -u
printf 'NewsHub CI cache summary (no secrets or cache contents)\n'
if [[ -n "${XDG_CACHE_HOME:-}" && -d "$XDG_CACHE_HOME" ]]; then
    timeout 8s du -sh "$XDG_CACHE_HOME/newshub-venvs" 2>/dev/null || printf 'backend cache size unavailable\n'
fi
if command -v docker >/dev/null 2>&1; then
    printf 'Docker build cache usage:\n'
    timeout 8s docker builder du 2>/dev/null | tail -n 4 || printf 'Docker cache usage unavailable\n'
fi
exit 0
