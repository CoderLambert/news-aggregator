#!/usr/bin/env bash
set -Eeuo pipefail

# Install frontend deps once per Node/npm/platform/package-lock fingerprint.
# npm's integrity-checking download cache is persisted separately.
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
FRONTEND="$PROJECT_ROOT/frontend"
CACHE_ROOT="${CI_FRONTEND_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-node-modules}"
REFRESH="${1:-}"
case "$REFRESH" in
    ""|--refresh) ;;
    *) echo "Usage: bash ops/ci/install-frontend-deps.sh [--refresh]" >&2; exit 2 ;;
esac
[[ -f "$FRONTEND/package-lock.json" && -f "$FRONTEND/package.json" ]] || {
    echo "Missing frontend npm manifest and lock" >&2; exit 2;
}
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / && ! -L "$CACHE_ROOT" ]] || {
    echo "frontend cache root must be absolute and not a symlink" >&2; exit 2;
}
mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9

VERSION="frontend-cache-v2|${CI_FRONTEND_CACHE_REV:-1}|$(node --version)|$(npm --version)|$(uname -sm)"
KEY="$({ printf '%s\n' "$VERSION"; cat "$FRONTEND/package.json" "$FRONTEND/package-lock.json"; } | sha256sum | cut -d' ' -f1)"
[[ "$KEY" =~ ^[a-f0-9]{64}$ ]] || { echo "invalid frontend cache key" >&2; exit 2; }
CACHE_DIR="$CACHE_ROOT/$KEY"
STAMP="$CACHE_DIR/.newshub-ready"
NODE_LINK="$FRONTEND/node_modules"

healthy() {
    [[ ! -L "$CACHE_DIR" && -f "$STAMP" && "$(cat "$STAMP")" == "$KEY" ]] || return 1
    [[ -x "$CACHE_DIR/node_modules/.bin/vitest" && -x "$CACHE_DIR/node_modules/.bin/vite" ]] || return 1
    npm ls --prefix "$CACHE_DIR" --depth=0 >/dev/null 2>&1
}

if [[ "$REFRESH" == --refresh ]] || ! healthy; then
    printf 'NewsHub frontend dependency cache: MISS (%s)\n' "${KEY:0:16}"
    rm -rf -- "$CACHE_DIR"
    mkdir -p "$CACHE_DIR"
    cp -- "$FRONTEND/package.json" "$FRONTEND/package-lock.json" "$CACHE_DIR/"
    npm ci --prefix "$CACHE_DIR" --prefer-offline --no-audit
    npm ls --prefix "$CACHE_DIR" --depth=0
    printf '%s\n' "$KEY" > "$STAMP"
else
    printf 'NewsHub frontend dependency cache: HIT (%s), skipping npm ci\n' "${KEY:0:16}"
fi

if [[ -e "$NODE_LINK" || -L "$NODE_LINK" ]]; then
    if [[ -L "$NODE_LINK" ]]; then
        resolved="$(readlink -f "$NODE_LINK" || true)"
        [[ "$resolved" == "$CACHE_DIR/node_modules" || "$resolved" == "$CACHE_ROOT/"* ]] \
            || { echo "frontend/node_modules points outside managed cache; refusing to replace" >&2; exit 2; }
    fi
    rm -rf -- "$NODE_LINK"
fi
ln -s "$CACHE_DIR/node_modules" "$NODE_LINK"
test -x "$NODE_LINK/.bin/vite"
printf 'NewsHub frontend dependency cache: READY (%s)\n' "${KEY:0:16}"
