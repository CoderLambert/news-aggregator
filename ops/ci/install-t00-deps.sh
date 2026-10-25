#!/usr/bin/env bash
# Reuse pinned, credential-free T00 SDK/Proxy environments across trusted CI runs.
# The disposable report/DB/HOME remain per-run; only dependencies are cached.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
SDK_LOCK="$ROOT/tools/byok_t00_probe/requirements-sdk.lock"
PROXY_LOCK="$ROOT/tools/byok_t00_probe/requirements-proxy.lock"
PREPARE="$ROOT/tools/byok_t00_probe/prepare_proxy.py"
CACHE_ROOT="${CI_T00_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-t00-venvs}"
PIP_CACHE_DIR="${PIP_CACHE_DIR:-$CACHE_ROOT/.pip}"
STATUS_ONLY=false
CACHE_ONLY=false
for argument in "$@"; do
    case "$argument" in
        --status) STATUS_ONLY=true ;;
        --cache-only) CACHE_ONLY=true ;;
        *) echo 'Usage: install-t00-deps.sh [--cache-only] | --status' >&2; exit 2 ;;
    esac
done
if $STATUS_ONLY && $CACHE_ONLY; then
    echo '--status cannot be combined with install options' >&2; exit 2
fi
if ! $STATUS_ONLY && ! $CACHE_ONLY; then
    : "${GITHUB_OUTPUT:?T00 dependencies require the GitHub step output file}"
fi
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / && ! -L "$CACHE_ROOT" ]] || {
    echo 'T00 cache root must be an absolute, real private directory' >&2; exit 2;
}
[[ "$PIP_CACHE_DIR" == /* && "$PIP_CACHE_DIR" != / && ! -L "$PIP_CACHE_DIR" ]] || {
    echo 'T00 pip cache must be an absolute, real private directory' >&2; exit 2;
}
[[ -f "$SDK_LOCK" && -f "$PROXY_LOCK" && -f "$PREPARE" ]] || {
    echo 'T00 locks or Prisma preparation script are missing' >&2; exit 2;
}

# Keep the v1 key so validated legacy entries migrate without reinstalling.
VERSION="t00-cache-v1|${CI_T00_CACHE_REV:-1}|$(python3 -c 'import sys,platform;print(sys.version,sys.implementation.cache_tag,platform.machine())')|$(node --version)|$(uname -sm)"
KEY="$( { printf '%s\n' "$VERSION"; cat "$SDK_LOCK" "$PROXY_LOCK" "$PREPARE"; } | sha256sum | cut -d' ' -f1)"
[[ "$KEY" =~ ^[0-9a-f]{64}$ ]] || { echo 'invalid T00 cache key' >&2; exit 2; }
ENTRY="$CACHE_ROOT/$KEY"
STAMP="$ENTRY/.newshub-ready"
LEGACY_STAMP="$ENTRY/.ready"
CHECKSUMS="$ENTRY/.prisma-sha256"
SDK_PY="$ENTRY/sdk/bin/python"
PROXY_PY="$ENTRY/proxy/bin/python"
for dir in "$ENTRY" "$ENTRY/sdk" "$ENTRY/proxy"; do
    [[ ! -L "$dir" ]] || { echo 'T00 cache contains a symlink' >&2; exit 2; }
done

dependencies_healthy() {
    [[ -x "$SDK_PY" && -x "$PROXY_PY" ]] || return 1
    [[ -f "$ENTRY/proxy/t00-prisma/runtime.json" && -f "$ENTRY/proxy/t00-prisma/schema.prisma" ]] || return 1
    "$SDK_PY" -m pip check >/dev/null 2>&1 || return 1
    "$PROXY_PY" -m pip check >/dev/null 2>&1 || return 1
    "$SDK_PY" -c 'from importlib.metadata import version; version("openai"); version("anthropic")' >/dev/null 2>&1 || return 1
    "$PROXY_PY" -c 'from importlib.metadata import version; import json, pathlib, shutil, sys; from prisma import Prisma; assert version("litellm") == "1.105.0"; assert json.loads((pathlib.Path(sys.prefix) / "t00-prisma/runtime.json").read_text())["node"] == shutil.which("node")' >/dev/null 2>&1
}

healthy() {
    local marker="$STAMP"
    if [[ ! -e "$marker" && ! -L "$marker" ]]; then marker="$LEGACY_STAMP"; fi
    [[ -f "$marker" && ! -L "$marker" && "$(cat "$marker")" == "$KEY" ]] || return 1
    if [[ -e "$CHECKSUMS" || -L "$CHECKSUMS" ]]; then
        [[ -f "$CHECKSUMS" && ! -L "$CHECKSUMS" ]] || return 1
        sha256sum --check --status "$CHECKSUMS" || return 1
    elif [[ "$marker" != "$LEGACY_STAMP" ]]; then
        return 1
    fi
    dependencies_healthy
}

status() {
    if healthy; then STATUS=HIT
    elif [[ -d "$ENTRY" ]]; then STATUS=PARTIAL
    else STATUS=MISSING
    fi
}
status
printf 'CACHE_KIND=t00\nSTATUS=%s\nKEY=%s\nROOT=%s\n' "$STATUS" "$KEY" "$CACHE_ROOT"
if $STATUS_ONLY; then exit 0; fi

mkdir -p "$CACHE_ROOT" "$PIP_CACHE_DIR"
chmod 700 "$CACHE_ROOT" "$PIP_CACHE_DIR"
export PIP_CACHE_DIR
# Shared by preparation, the complete protocol consumer, and unified GC.
[[ ! -L "$CACHE_ROOT/.install.lock" ]] || { echo 'T00 install lock is a symlink' >&2; exit 2; }
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9
status
if [[ "$STATUS" == HIT ]]; then
    echo "NewsHub T00 dependency cache: HIT (${KEY:0:16})"
else
    echo "NewsHub T00 dependency cache: MISS (${KEY:0:16})"
    # Only remove the validated, content-addressed entry; never shared cache roots.
    rm -rf -- "$ENTRY"
    mkdir -m 700 -- "$ENTRY"
    python3 -m venv "$ENTRY/sdk"
    python3 -m venv "$ENTRY/proxy"
    "$SDK_PY" -m pip install --disable-pip-version-check --no-input -r "$SDK_LOCK"
    "$PROXY_PY" -m pip install --disable-pip-version-check --no-input -r "$PROXY_LOCK"
    "$PROXY_PY" "$PREPARE"
    dependencies_healthy || { echo 'T00 dependency validation failed' >&2; exit 1; }
fi

# Publish only validated success, including migration from the legacy .ready.
sha256sum "$ENTRY/proxy/t00-prisma/runtime.json" "$ENTRY/proxy/t00-prisma/schema.prisma" > "$CHECKSUMS.tmp.$$"
mv -f -- "$CHECKSUMS.tmp.$$" "$CHECKSUMS"
printf '%s\n' "$KEY" > "$STAMP.tmp.$$"
mv -f -- "$STAMP.tmp.$$" "$STAMP"
printf '%s\n' "$KEY" > "$CACHE_ROOT/.current-key.tmp.$$"
mv -f -- "$CACHE_ROOT/.current-key.tmp.$$" "$CACHE_ROOT/.current-key"
if ! $CACHE_ONLY; then
    # These are dependency interpreter paths, never credentials or runtime data.
    printf 'sdk_python=%s\nproxy_python=%s\n' "$SDK_PY" "$PROXY_PY" >> "$GITHUB_OUTPUT"
fi
echo "NewsHub T00 dependency cache: READY (${KEY:0:16})"
