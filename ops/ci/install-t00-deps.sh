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
: "${GITHUB_OUTPUT:?T00 dependencies require the GitHub step output file}"
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / && ! -L "$CACHE_ROOT" ]] || {
    echo 'T00 cache root must be an absolute, real private directory' >&2; exit 2;
}
[[ -f "$SDK_LOCK" && -f "$PROXY_LOCK" && -f "$PREPARE" ]] || {
    echo 'T00 locks or Prisma preparation script are missing' >&2; exit 2;
}
mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
PIP_CACHE_DIR="$CACHE_ROOT/.pip"
[[ ! -L "$PIP_CACHE_DIR" ]] || { echo 'T00 pip cache is a symlink' >&2; exit 2; }
mkdir -p "$PIP_CACHE_DIR"
chmod 700 "$PIP_CACHE_DIR"
export PIP_CACHE_DIR
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9

# Cache is tied to the pinned inputs and both Python and Node ABI/toolchain.
VERSION="t00-cache-v1|${CI_T00_CACHE_REV:-1}|$(python3 -c 'import sys,platform;print(sys.version,sys.implementation.cache_tag,platform.machine())')|$(node --version)|$(uname -sm)"
KEY="$( { printf '%s\n' "$VERSION"; cat "$SDK_LOCK" "$PROXY_LOCK" "$PREPARE"; } | sha256sum | cut -d' ' -f1)"
[[ "$KEY" =~ ^[0-9a-f]{64}$ ]] || { echo 'invalid T00 cache key' >&2; exit 2; }
ENTRY="$CACHE_ROOT/$KEY"
STAMP="$ENTRY/.ready"
SDK_PY="$ENTRY/sdk/bin/python"
PROXY_PY="$ENTRY/proxy/bin/python"
for dir in "$ENTRY" "$ENTRY/sdk" "$ENTRY/proxy"; do
    [[ ! -L "$dir" ]] || { echo 'T00 cache contains a symlink' >&2; exit 2; }
done

healthy() {
    [[ -f "$STAMP" && ! -L "$STAMP" && "$(cat "$STAMP")" == "$KEY" ]] || return 1
    [[ -x "$SDK_PY" && -x "$PROXY_PY" ]] || return 1
    [[ -f "$ENTRY/proxy/t00-prisma/runtime.json" && -f "$ENTRY/proxy/t00-prisma/schema.prisma" ]] || return 1
    "$SDK_PY" -m pip check >/dev/null 2>&1 || return 1
    "$PROXY_PY" -m pip check >/dev/null 2>&1 || return 1
    "$SDK_PY" -c 'from importlib.metadata import version; version("openai"); version("anthropic")' >/dev/null 2>&1 || return 1
    "$PROXY_PY" -c 'from importlib.metadata import version; assert version("litellm") == "1.105.0"' >/dev/null 2>&1
}

if healthy; then
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
    "$SDK_PY" -m pip check
    "$PROXY_PY" -m pip check
    # Stamp only after all dependency and generator operations succeed.
    printf '%s\n' "$KEY" > "$STAMP"
fi

# These are dependency interpreter paths, never credentials or runtime data.
printf 'sdk_python=%s\nproxy_python=%s\n' "$SDK_PY" "$PROXY_PY" >> "$GITHUB_OUTPUT"
echo "NewsHub T00 dependency cache: READY (${KEY:0:16})"
