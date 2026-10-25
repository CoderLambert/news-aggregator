#!/usr/bin/env bash
set -Eeuo pipefail

# Content-addressed, validated backend virtualenv. Only trusted same-repo CI
# is permitted to reuse this persistent workspace.
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$PROJECT_ROOT"
REQ="$PROJECT_ROOT/backend/requirements.txt"
LOCK="$PROJECT_ROOT/backend/requirements-ci.lock"
CHECKER="$PROJECT_ROOT/ops/ci/check-backend-lock.py"
TORCH_PIN="2.14.1+cpu"
PLAYWRIGHT_PIN="1.62.0"
CACHE_ROOT="${CI_BACKEND_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-venvs}"
PIP_CACHE_DIR="${PIP_CACHE_DIR:-$CACHE_ROOT/.pip}"
REFRESH=false
STATUS_ONLY=false
CACHE_ONLY=false

for argument in "$@"; do
    case "$argument" in
        --refresh) REFRESH=true ;;
        --status) STATUS_ONLY=true ;;
        --cache-only) CACHE_ONLY=true ;;
        *)
            echo "Usage: bash ops/ci/install-backend-deps.sh [--refresh] [--cache-only] | --status" >&2
            exit 2
            ;;
    esac
done
if $STATUS_ONLY && { $REFRESH || $CACHE_ONLY; }; then
    echo "--status cannot be combined with install options" >&2
    exit 2
fi
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / ]] || { echo "cache root must be absolute" >&2; exit 2; }
[[ ! -L "$CACHE_ROOT" ]] || { echo "cache root must not be a symlink" >&2; exit 2; }
[[ "$PIP_CACHE_DIR" == /* && "$PIP_CACHE_DIR" != / ]] || { echo "pip cache must be absolute" >&2; exit 2; }
[[ ! -L "$PIP_CACHE_DIR" ]] || { echo "pip cache must not be a symlink" >&2; exit 2; }
[[ -f "$REQ" && -f "$LOCK" && -f "$CHECKER" ]] || {
    echo "backend requirements, CI lock or lock checker missing" >&2; exit 2;
}
python3 "$CHECKER" "$REQ" "$LOCK"

# Direct requirements + complete CI lock, Python ABI, architecture and torch pin form the cache key.
# Bump CI_BACKEND_CACHE_REV to invalidate old environments deliberately.
VERSION="backend-cache-v3|${CI_BACKEND_CACHE_REV:-1}|$TORCH_PIN|$PLAYWRIGHT_PIN|$(python3 -c 'import sys,platform;print(sys.implementation.cache_tag,platform.machine())')"
KEY="$({ printf '%s\n' "$VERSION"; cat "$REQ" "$LOCK"; } | sha256sum | cut -d' ' -f1)"
[[ "$KEY" =~ ^[a-f0-9]{64}$ ]] || { echo "invalid backend cache key" >&2; exit 2; }
ENV_DIR="$CACHE_ROOT/$KEY"
STAMP="$ENV_DIR/.newshub-ready"
VENV_LINK="$PROJECT_ROOT/backend/venv"

cache_healthy() {
    [[ -f "$STAMP" && ! -L "$ENV_DIR" && -x "$ENV_DIR/bin/python" ]] || return 1
    [[ "$(cat "$STAMP")" == "$KEY" ]] || return 1
    "$ENV_DIR/bin/python" -m pip check >/dev/null 2>&1 || return 1
    "$ENV_DIR/bin/python" "$CHECKER" "$REQ" "$LOCK" --installed >/dev/null 2>&1
}

if cache_healthy; then
    STATUS=HIT
elif [[ -d "$ENV_DIR" && ! -L "$ENV_DIR" ]]; then
    STATUS=PARTIAL
else
    STATUS=MISSING
fi
printf 'CACHE_KIND=backend\nSTATUS=%s\nKEY=%s\nROOT=%s\n' "$STATUS" "$KEY" "$CACHE_ROOT"

if $STATUS_ONLY; then
    exit 0
fi

mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
mkdir -p "$PIP_CACHE_DIR"
chmod 700 "$PIP_CACHE_DIR"
export PIP_CACHE_DIR
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9

# Recheck after taking the lock because another maintenance process may have
# completed the same content-addressed environment while this process waited.
if cache_healthy; then
    STATUS=HIT
elif [[ -d "$ENV_DIR" && ! -L "$ENV_DIR" ]]; then
    STATUS=PARTIAL
else
    STATUS=MISSING
fi

if $REFRESH || [[ "$STATUS" != HIT ]]; then
    if ! $REFRESH && [[ "$STATUS" == PARTIAL && -x "$ENV_DIR/bin/python" ]]; then
        # An interrupted pip run leaves a usable partial venv. Resume in place:
        # pip skips satisfied packages and the persistent download cache supplies
        # completed wheels, avoiding another large torch/package download.
        printf 'NewsHub backend dependency cache: RESUME (%s)\n' "${KEY:0:16}"
    else
        printf 'NewsHub backend dependency cache: MISS (%s)\n' "${KEY:0:16}"
        # The only removable directory is the checked content-addressed entry.
        rm -rf -- "$ENV_DIR"
        python3 -m venv "$ENV_DIR"
    fi
    rm -f -- "$STAMP.tmp"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check \
        --index-url https://download.pytorch.org/whl/cpu "torch==$TORCH_PIN"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$LOCK"
    "$ENV_DIR/bin/python" -m pip install --disable-pip-version-check "playwright==$PLAYWRIGHT_PIN"
    "$ENV_DIR/bin/python" -m pip check
    "$ENV_DIR/bin/python" "$CHECKER" "$REQ" "$LOCK" --installed
    "$ENV_DIR/bin/python" -m pip freeze > "$ENV_DIR/newshub-freeze.txt"
    printf '%s\n' "$KEY" > "$STAMP.tmp"
    mv -f -- "$STAMP.tmp" "$STAMP"
else
    printf 'NewsHub backend dependency cache: HIT (%s), skipping torch/pip installs\n' "${KEY:0:16}"
fi

CURRENT_TMP="$CACHE_ROOT/.current-key.tmp.$$"
printf '%s\n' "$KEY" > "$CURRENT_TMP"
mv -f -- "$CURRENT_TMP" "$CACHE_ROOT/.current-key"

if $CACHE_ONLY; then
    "$ENV_DIR/bin/python" -m pip check
    printf 'NewsHub backend dependency cache: READY (%s, cache-only)\n' "${KEY:0:16}"
    exit 0
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
