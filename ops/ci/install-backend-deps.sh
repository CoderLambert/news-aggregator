#!/usr/bin/env bash
set -Eeuo pipefail

# Content-addressed, validated backend virtualenv. Only trusted same-repo CI
# is permitted to reuse this persistent workspace.
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$PROJECT_ROOT"
REQ="$PROJECT_ROOT/backend/requirements.txt"
TORCH_PIN="2.14.1+cpu"
PLAYWRIGHT_PIN="1.62.0"
CACHE_ROOT="${CI_BACKEND_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-venvs}"
REFRESH="${1:-}"

case "$REFRESH" in
    ""|--refresh) ;;
    *) echo "Usage: bash ops/ci/install-backend-deps.sh [--refresh]" >&2; exit 2 ;;
esac
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / ]] || { echo "cache root must be absolute" >&2; exit 2; }
[[ ! -L "$CACHE_ROOT" ]] || { echo "cache root must not be a symlink" >&2; exit 2; }
[[ -f "$REQ" ]] || { echo "backend/requirements.txt missing" >&2; exit 2; }
mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9

# Requirements content, Python ABI, architecture and torch pin form cache key.
# Bump CI_BACKEND_CACHE_REV to invalidate old environments deliberately.
VERSION="backend-cache-v3|${CI_BACKEND_CACHE_REV:-1}|$TORCH_PIN|$PLAYWRIGHT_PIN|$(python3 -c 'import sys,platform;print(sys.implementation.cache_tag,platform.machine())')"
KEY="$({ printf '%s\n' "$VERSION"; cat "$REQ"; } | sha256sum | cut -d' ' -f1)"
[[ "$KEY" =~ ^[a-f0-9]{64}$ ]] || { echo "invalid backend cache key" >&2; exit 2; }
ENV_DIR="$CACHE_ROOT/$KEY"
STAMP="$ENV_DIR/.newshub-ready"
VENV_LINK="$PROJECT_ROOT/backend/venv"

cache_healthy() {
    [[ -f "$STAMP" && ! -L "$ENV_DIR" && -x "$ENV_DIR/bin/python" ]] || return 1
    [[ "$(cat "$STAMP")" == "$KEY" ]] || return 1
    "$ENV_DIR/bin/python" -m pip check >/dev/null 2>&1 || return 1
    "$ENV_DIR/bin/python" -c 'from importlib.metadata import version; assert version("torch")=="2.14.1+cpu" and version("playwright")=="1.62.0"' >/dev/null 2>&1
}

if [[ "$REFRESH" == --refresh ]] || ! cache_healthy; then
    printf 'NewsHub backend dependency cache: MISS (%s)\n' "${KEY:0:16}"
    # The only removable directory is the checked content-addressed entry.
    rm -rf -- "$ENV_DIR"
    python3 -m venv "$ENV_DIR"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check \
        --index-url https://download.pytorch.org/whl/cpu "torch==$TORCH_PIN"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$REQ"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check "playwright==$PLAYWRIGHT_PIN"
    "$ENV_DIR/bin/python" -m pip check
    "$ENV_DIR/bin/python" -c 'from importlib.metadata import version; assert version("torch")=="2.14.1+cpu" and version("playwright")=="1.62.0"'
    "$ENV_DIR/bin/python" -m pip freeze > "$ENV_DIR/newshub-freeze.txt"
    printf '%s\n' "$KEY" > "$STAMP"
else
    printf 'NewsHub backend dependency cache: HIT (%s), skipping torch/pip installs\n' "${KEY:0:16}"
fi

# Existing pipeline references backend/venv/bin/python. Store the real
# environment outside checkout, but keep that compatible symlink.
if [[ -e "$VENV_LINK" || -L "$VENV_LINK" ]]; then
    if [[ -L "$VENV_LINK" ]]; then
        resolved="$(readlink -f "$VENV_LINK" || true)"
        [[ "$resolved" == "$ENV_DIR" || "$resolved" == "$CACHE_ROOT/"* ]] \
            || { echo "backend/venv points outside managed cache; refusing to replace" >&2; exit 2; }
    fi
    rm -rf -- "$VENV_LINK"
fi
ln -s "$ENV_DIR" "$VENV_LINK"
"$VENV_LINK/bin/python" -m pip check
printf 'NewsHub backend dependency cache: READY (%s)\n' "${KEY:0:16}"
