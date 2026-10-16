#!/usr/bin/env bash
# Opt-in, full-coverage benchmark. Never modify the shared backend venv or
# existing pytest defaults. All three test roots run in each xdist repetition.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
PYTHON="$ROOT/backend/venv/bin/python"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/newshub-xdist"
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / && ! -L "$CACHE_ROOT" ]] || {
    echo 'xdist cache root must be absolute and not a symlink' >&2; exit 2;
}
[[ -x "$PYTHON" && -d "${TMPDIR:-}" ]] || {
    echo 'backend venv and private TMPDIR must already exist' >&2; exit 2;
}
REPEATS="${CI_XDIST_REPEATS:-3}"
[[ "$REPEATS" =~ ^[123]$ ]] || { echo 'CI_XDIST_REPEATS must be 1..3' >&2; exit 2; }
KEY="$(printf 'xdist-3.8.0|execnet-2.1.1|%s\n' "$("$PYTHON" -c 'import sys; print(sys.implementation.cache_tag)')" | sha256sum | cut -d' ' -f1)"
CACHE="$CACHE_ROOT/$KEY"
mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9
healthy() {
    [[ -d "$CACHE" && ! -L "$CACHE" && -f "$CACHE/.ready" ]] || return 1
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -c \
        'from importlib.metadata import version; assert version("pytest-xdist") == "3.8.0" and version("execnet") == "2.1.1"' \
        >/dev/null 2>&1
}
if ! healthy; then
    [[ "$KEY" =~ ^[a-f0-9]{64}$ ]] || exit 2
    rm -rf -- "$CACHE"
    mkdir -p "$CACHE"
    "$PYTHON" -m pip install --disable-pip-version-check --no-deps --only-binary=:all: \
        --target "$CACHE" pytest-xdist==3.8.0 execnet==2.1.1
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -c \
        'from importlib.metadata import version; assert version("pytest-xdist") == "3.8.0" and version("execnet") == "2.1.1"'
    touch "$CACHE/.ready"
fi
flock -u 9
REPORT="$(mktemp -d "${TMPDIR}/newshub-xdist-benchmark.XXXXXX")"
printf 'xdist-benchmark: repeats=%s workers=2 dist=loadfile report=%s\n' "$REPEATS" "$REPORT"
for i in $(seq 1 "$REPEATS"); do
    start="$(date +%s)"
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -m pytest \
        -q -n 2 --dist=loadfile --max-worker-restart=0 \
        --durations=25 --junitxml="$REPORT/round-$i.xml" \
        tests/ backend/api/tests/ scripts/deploy/tests/
    elapsed=$(( $(date +%s) - start ))
    printf 'xdist-benchmark: round %s/%s PASS elapsed=%ss\n' "$i" "$REPEATS" "$elapsed"
done
echo 'xdist-benchmark: all complete test roots passed without retries'
