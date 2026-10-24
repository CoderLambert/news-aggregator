#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
EXECUTE=0
PROJECT=""
SERVICE="app"
ROOT="${NEWSHUB_TEST_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-test-acceptance}/frontend-preview"
WAIT_TIMEOUT=120
COMPOSE_FILES=()
STAGE_DIR=""
CURRENT_TMP=""
PREVIOUS_TMP=""
OVERRIDE_TMP=""

usage() {
    cat <<'EOF'
Usage: local-frontend-preview.sh [--execute] --project NAME --compose ABSOLUTE_FILE [--compose ABSOLUTE_FILE ...] [--root ABSOLUTE_DIR]

Builds a content-addressed frontend release with the existing Node environment and,
with --execute, mounts it read-only at /app/frontend/dist and recreates app together
with services that share its network namespace.
Without --execute, validates inputs and prints the planned release; Docker is not used.
EOF
}

fail() {
    printf 'local-frontend-preview: %s\n' "$1" >&2
    exit 2
}

cleanup() {
    local exit_status=${1:-$?}
    trap - EXIT
    if [[ -n "$STAGE_DIR" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "$STAGE_DIR"
    fi
    [[ -z "$CURRENT_TMP" || ! -L "$CURRENT_TMP" ]] || rm -f -- "$CURRENT_TMP"
    [[ -z "$PREVIOUS_TMP" || ! -L "$PREVIOUS_TMP" ]] || rm -f -- "$PREVIOUS_TMP"
    [[ -z "$OVERRIDE_TMP" || ! -f "$OVERRIDE_TMP" ]] || rm -f -- "$OVERRIDE_TMP"
    exit "$exit_status"
}
trap cleanup EXIT

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --project) (($# >= 2)) || fail '--project requires a value.'; PROJECT=$2; shift 2 ;;
        --compose) (($# >= 2)) || fail '--compose requires a value.'; COMPOSE_FILES+=("$2"); shift 2 ;;
        --root) (($# >= 2)) || fail '--root requires a value.'; ROOT=$2; shift 2 ;;
        --wait-timeout) (($# >= 2)) || fail '--wait-timeout requires a value.'; WAIT_TIMEOUT=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[[ "$PROJECT" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || fail '--project must be a safe Compose project name.'
[[ "$WAIT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || fail '--wait-timeout must be a positive integer.'
((${#COMPOSE_FILES[@]} > 0)) || fail 'at least one --compose file is required.'
[[ "$ROOT" == /* && "$ROOT" != / ]] || fail '--root must be an absolute path other than /.'
[[ "$ROOT" != *$'\n'* && "$ROOT" != *$'\r'* && "$ROOT" != *"'"* ]] || fail '--root contains unsupported YAML characters.'
[[ ! -L "$ROOT" ]] || fail '--root must not be a symlink.'
ROOT="$(realpath -m -- "$ROOT")"
[[ "$ROOT" != *$'\n'* && "$ROOT" != *$'\r'* && "$ROOT" != *"'"* ]] || fail '--root resolves to unsupported YAML characters.'
[[ "$ROOT" != "$PROJECT_ROOT" && "$ROOT" != "$PROJECT_ROOT/"* ]] || fail '--root must be outside the source tree.'
for compose_file in "${COMPOSE_FILES[@]}"; do
    [[ "$compose_file" == /* && -f "$compose_file" && ! -L "$compose_file" ]] \
        || fail 'each --compose path must be an absolute regular file.'
done
[[ -x "$FRONTEND_DIR/node_modules/.bin/tsc" && -x "$FRONTEND_DIR/node_modules/.bin/vite" ]] \
    || fail 'compatible frontend/node_modules is missing; refusing to install dependencies.'

if command -v mise >/dev/null 2>&1; then
    NODE_RUNNER=(mise exec node@22 --)
elif command -v node >/dev/null 2>&1 && [[ "$(node --version)" == v22.* ]]; then
    NODE_RUNNER=()
else
    fail 'Node 22 is unavailable; refusing to install or change the host runtime.'
fi
NODE_VERSION="$("${NODE_RUNNER[@]}" node --version)"
[[ "$NODE_VERSION" == v22.* ]] || fail 'the selected Node runtime is not version 22.'

SOURCE_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/newshub-frontend-manifest.XXXXXX")"
trap 'exit_status=$?; rm -f -- "$SOURCE_MANIFEST"; cleanup "$exit_status"' EXIT
while IFS= read -r -d '' source_file; do
    case "$source_file" in
        frontend/dist/*|frontend/node_modules/*|frontend/.env|frontend/.env.*) continue ;;
    esac
    [[ "$source_file" != *$'\n'* && "$source_file" != *$'\r'* ]] \
        || fail 'frontend input paths must not contain newlines.'
    [[ -f "$PROJECT_ROOT/$source_file" && ! -L "$PROJECT_ROOT/$source_file" ]] \
        || fail "frontend input is not a regular file: $source_file"
    printf '%s  %s\n' "$(sha256sum -- "$PROJECT_ROOT/$source_file" | cut -d' ' -f1)" "$source_file" >> "$SOURCE_MANIFEST"
done < <(git -C "$PROJECT_ROOT" ls-files -co --exclude-standard -z -- frontend)
[[ -s "$SOURCE_MANIFEST" ]] || fail 'no frontend source inputs were found.'
FINGERPRINT="$({ printf 'node=%s\n' "$NODE_VERSION"; cat "$SOURCE_MANIFEST"; } | sha256sum | cut -d' ' -f1)"
[[ "$FINGERPRINT" =~ ^[0-9a-f]{64}$ ]] || fail 'could not compute a frontend fingerprint.'
RELEASE="$ROOT/releases/$FINGERPRINT"
DIST="$RELEASE/dist"
PROJECT_DIR="$ROOT/projects/$PROJECT"
OVERRIDE="$PROJECT_DIR/releases/$FINGERPRINT.yaml"

if ((!EXECUTE)); then
    printf 'Dry run only: frontend %s would use release %s and recreate service %s plus its network-sharing sidecars in project %s.\n' \
        "$FINGERPRINT" "$RELEASE" "$SERVICE" "$PROJECT"
    exit 0
fi

mkdir -p -- "$ROOT/releases" "$PROJECT_DIR/releases"
[[ -d "$ROOT" && ! -L "$ROOT" && -d "$ROOT/releases" && ! -L "$ROOT/releases" ]] \
    || fail 'release root must contain real directories.'

validate_dist() {
    local dist=$1
    [[ -f "$dist/index.html" && ! -L "$dist/index.html" ]] || fail 'frontend release is missing index.html.'
    [[ -d "$dist/assets" && ! -L "$dist/assets" ]] || fail 'frontend release is missing assets/.'
    find "$dist/assets" -type f -print -quit | grep -q . || fail 'frontend release assets/ is empty.'
    ! find "$dist" -type l -print -quit | grep -q . || fail 'frontend release must not contain symlinks.'
    ! find "$dist" ! -type f ! -type d -print -quit | grep -q . || fail 'frontend release contains unsupported file types.'
}

if [[ -e "$RELEASE" || -L "$RELEASE" ]]; then
    [[ -d "$RELEASE" && ! -L "$RELEASE" ]] || fail 'existing release path is not a real directory.'
    validate_dist "$DIST"
    [[ -f "$RELEASE/manifest.sha256" ]] || fail 'existing release has no source manifest.'
    cmp -s -- "$SOURCE_MANIFEST" "$RELEASE/manifest.sha256" || fail 'existing release fingerprint has different inputs.'
    printf 'Reusing frontend release %s.\n' "$FINGERPRINT"
else
    STAGE_DIR="$(mktemp -d "$ROOT/releases/.${FINGERPRINT}.tmp.XXXXXX")"
    (
        cd -- "$FRONTEND_DIR"
        "${NODE_RUNNER[@]}" ./node_modules/.bin/tsc --noEmit
        "${NODE_RUNNER[@]}" ./node_modules/.bin/vite build --outDir "$STAGE_DIR/dist" --emptyOutDir
    )
    validate_dist "$STAGE_DIR/dist"
    cp -- "$SOURCE_MANIFEST" "$STAGE_DIR/manifest.sha256"
    printf 'node=%s\nfingerprint=%s\n' "$NODE_VERSION" "$FINGERPRINT" > "$STAGE_DIR/release.meta"
    find "$STAGE_DIR" -type d -exec chmod 755 -- {} +
    find "$STAGE_DIR" -type f -exec chmod 644 -- {} +
    mv -- "$STAGE_DIR" "$RELEASE"
    STAGE_DIR=""
fi

OVERRIDE_TMP="$(mktemp "$PROJECT_DIR/releases/.${FINGERPRINT}.override.XXXXXX")"
cat > "$OVERRIDE_TMP" <<EOF
services:
  $SERVICE:
    volumes:
      - type: bind
        source: '$DIST'
        target: /app/frontend/dist
        read_only: true
EOF
chmod 644 -- "$OVERRIDE_TMP"
mv -f -- "$OVERRIDE_TMP" "$OVERRIDE"
OVERRIDE_TMP=""

COMPOSE=(docker compose -p "$PROJECT")
for compose_file in "${COMPOSE_FILES[@]}"; do COMPOSE+=(-f "$compose_file"); done
BASE_COMPOSE=("${COMPOSE[@]}")
COMPOSE+=(-f "$OVERRIDE")
"${COMPOSE[@]}" config --quiet
if ! SHARED_NETWORK_SERVICES="$("${COMPOSE[@]}" config --format json | python3 -c '
import json
import re
import sys

target = sys.argv[1]
document = json.load(sys.stdin)
services = document.get("services")
if not isinstance(services, dict) or target not in services:
    raise SystemExit("target service is missing from Compose config")
safe = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
for name in sorted(services):
    if not safe.fullmatch(name):
        raise SystemExit("unsafe service name in Compose config")
    config = services[name]
    if isinstance(config, dict) and config.get("network_mode") == f"service:{target}":
        print(name)
' "$SERVICE")"; then
    fail 'could not identify services that share the app network namespace.'
fi
RECREATE_SERVICES=("$SERVICE")
while IFS= read -r sidecar; do
    [[ -z "$sidecar" ]] || RECREATE_SERVICES+=("$sidecar")
done <<< "$SHARED_NETWORK_SERVICES"
CONTAINER_ID="$("${BASE_COMPOSE[@]}" ps -q "$SERVICE")"
[[ -n "$CONTAINER_ID" ]] || fail "service $SERVICE is not running in project $PROJECT."
OLD_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$CONTAINER_ID")"

old_current=""
if [[ -L "$PROJECT_DIR/current" ]]; then
    old_current="$(realpath -e -- "$PROJECT_DIR/current")" || fail 'current preview override is broken.'
    [[ "$old_current" == "$PROJECT_DIR/releases/"*.yaml ]] || fail 'current preview override escapes its release directory.'
elif [[ -e "$PROJECT_DIR/current" ]]; then
    fail 'current preview marker is not a symlink.'
fi

restore_configuration() {
    if [[ -n "$old_current" ]]; then
        "${BASE_COMPOSE[@]}" -f "$old_current" up -d --no-deps --force-recreate --wait \
            --wait-timeout "$WAIT_TIMEOUT" "${RECREATE_SERVICES[@]}"
    else
        "${BASE_COMPOSE[@]}" up -d --no-deps --force-recreate --wait \
            --wait-timeout "$WAIT_TIMEOUT" "${RECREATE_SERVICES[@]}"
    fi
}

restore_and_fail() {
    local message=$1
    restore_configuration || true
    fail "$message"
}

if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate --wait --wait-timeout "$WAIT_TIMEOUT" "${RECREATE_SERVICES[@]}"; then
    restore_and_fail 'frontend preview activation failed; attempted to restore the previous app configuration.'
fi

if ! CONTAINER_ID="$("${COMPOSE[@]}" ps -q "$SERVICE")" || [[ -z "$CONTAINER_ID" ]]; then
    restore_and_fail "service $SERVICE was not running after frontend preview activation."
fi
if ! NEW_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$CONTAINER_ID")"; then
    restore_and_fail 'could not inspect the activated app image.'
fi
[[ "$NEW_IMAGE_ID" == "$OLD_IMAGE_ID" ]] \
    || restore_and_fail 'frontend-only activation unexpectedly changed the backend image.'
if ! MOUNT="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/frontend/dist"}}{{.Source}}|{{.RW}}{{end}}{{end}}' "$CONTAINER_ID")"; then
    restore_and_fail 'could not inspect the activated frontend mount.'
fi
[[ "$MOUNT" == "$DIST|false" ]] \
    || restore_and_fail 'running app does not have the expected read-only frontend mount.'

if [[ -n "$old_current" ]]; then
    PREVIOUS_TMP="$PROJECT_DIR/.previous.new.$$"
    ln -s "${old_current#"$PROJECT_DIR/"}" "$PREVIOUS_TMP"
    mv -Tf -- "$PREVIOUS_TMP" "$PROJECT_DIR/previous"
    PREVIOUS_TMP=""
fi
CURRENT_TMP="$PROJECT_DIR/.current.new.$$"
ln -s "releases/$FINGERPRINT.yaml" "$CURRENT_TMP"
mv -Tf -- "$CURRENT_TMP" "$PROJECT_DIR/current"
CURRENT_TMP=""
printf 'Activated frontend %s from %s on project %s; recreated services [%s]; backend image unchanged (%s).\n' \
    "$FINGERPRINT" "$DIST" "$PROJECT" "${RECREATE_SERVICES[*]}" "$NEW_IMAGE_ID"
