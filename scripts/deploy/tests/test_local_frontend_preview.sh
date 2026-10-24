#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd -P)"
SCRIPT="$PROJECT_ROOT/scripts/deploy/local-frontend-preview.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/newshub-frontend-preview-test.XXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT

fail() {
    printf 'test_local_frontend_preview: %s\n' "$1" >&2
    exit 1
}

expect_failure() {
    local expected=$1
    shift
    local output
    if output="$("$@" 2>&1)"; then
        fail "command unexpectedly succeeded: $*; output: $output"
    fi
    [[ "$output" == *"$expected"* ]] || fail "missing failure text '$expected': $output"
}

cat > "$TMP/compose.yaml" <<'YAML'
services:
  app:
    image: synthetic.invalid/newshub:test
  ai-gateway:
    image: synthetic.invalid/gateway:test
    network_mode: service:app
  channel-worker:
    image: synthetic.invalid/worker:test
    network_mode: service:app
  translation-redis:
    image: synthetic.invalid/redis:test
    network_mode: service:app
  database:
    image: synthetic.invalid/database:test
YAML

mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'SH'
#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [ "$1" = inspect ]; then
    case "$3" in
        *Image*) printf '%s\n' 'sha256:synthetic-app-image' ;;
        *Mounts*)
            override=$(cat "$FAKE_DOCKER_OVERRIDE")
            source_path=$(sed -n "s/^[[:space:]]*source: '\(.*\)'$/\1/p" "$override")
            printf '%s|false\n' "$source_path"
            ;;
        *) exit 1 ;;
    esac
    exit 0
fi
[ "$1" = compose ] || exit 1
shift
case " $* " in
    *" config --format json "*)
        cat "$FAKE_DOCKER_CONFIG"
        ;;
    *" config --quiet "*) ;;
    *" ps -q app "*) printf '%s\n' 'synthetic-app-container' ;;
    *" up -d "*)
        previous=''
        for value in "$@"; do
            if [ "$previous" = -f ] && [ "${value##*/}" != compose.yaml ]; then
                printf '%s\n' "$value" > "$FAKE_DOCKER_OVERRIDE"
            fi
            previous=$value
        done
        if [ -e "$FAKE_DOCKER_FAIL_NEXT" ]; then
            rm -f "$FAKE_DOCKER_FAIL_NEXT"
            exit 1
        fi
        ;;
    *) exit 1 ;;
esac
SH
chmod +x "$TMP/bin/docker"

bash -n "$SCRIPT"
"$SCRIPT" --help | grep -q 'mounts it read-only at /app/frontend/dist'

output="$($SCRIPT \
    --project preview-test \
    --compose "$TMP/compose.yaml" \
    --root "$TMP/releases")"
[[ "$output" == Dry\ run\ only:* ]] || fail "unexpected dry-run output: $output"
[[ ! -e "$TMP/releases" ]] || fail 'dry-run created the release root.'

expect_failure '--project must be a safe Compose project name.' \
    "$SCRIPT" --project '../unsafe' --compose "$TMP/compose.yaml" --root "$TMP/releases"
expect_failure '--root must be outside the source tree.' \
    "$SCRIPT" --project preview-test --compose "$TMP/compose.yaml" --root "$PROJECT_ROOT/.preview-test"
expect_failure 'each --compose path must be an absolute regular file.' \
    "$SCRIPT" --project preview-test --compose compose.yaml --root "$TMP/releases"
ln -s "$TMP/releases-target" "$TMP/releases-link"
expect_failure '--root must not be a symlink.' \
    "$SCRIPT" --project preview-test --compose "$TMP/compose.yaml" --root "$TMP/releases-link"
expect_failure 'unknown argument: --service' \
    "$SCRIPT" --project preview-test --compose "$TMP/compose.yaml" --root "$TMP/releases" --service indexer

FAKE_DOCKER_LOG="$TMP/docker.log"
FAKE_DOCKER_OVERRIDE="$TMP/docker.override"
FAKE_DOCKER_FAIL_NEXT="$TMP/docker.fail-next"
FAKE_DOCKER_CONFIG="$TMP/docker-config.json"
cat > "$FAKE_DOCKER_CONFIG" <<'JSON'
{"services":{"app":{"image":"synthetic.invalid/newshub:test"},"ai-gateway":{"network_mode":"service:app"},"channel-worker":{"network_mode":"service:app"},"translation-redis":{"network_mode":"service:app"},"database":{"image":"synthetic.invalid/database:test"}}}
JSON
export FAKE_DOCKER_LOG FAKE_DOCKER_OVERRIDE FAKE_DOCKER_FAIL_NEXT FAKE_DOCKER_CONFIG
PATH="$TMP/bin:$PATH" "$SCRIPT" --execute \
    --project preview-test \
    --compose "$TMP/compose.yaml" \
    --root "$TMP/releases" \
    --wait-timeout 5

activation=$(grep ' up -d ' "$FAKE_DOCKER_LOG" | tail -1)
[[ "$activation" == *' app ai-gateway channel-worker translation-redis' ]] \
    || fail "activation did not recreate app network sidecars: $activation"

: > "$FAKE_DOCKER_LOG"
touch "$FAKE_DOCKER_FAIL_NEXT"
expect_failure 'frontend preview activation failed; attempted to restore the previous app configuration.' \
    env PATH="$TMP/bin:$PATH" "$SCRIPT" --execute \
        --project preview-test \
        --compose "$TMP/compose.yaml" \
        --root "$TMP/releases" \
        --wait-timeout 5
mapfile -t recovery_commands < <(grep ' up -d ' "$FAKE_DOCKER_LOG")
[[ ${#recovery_commands[@]} -eq 2 ]] || fail 'activation failure did not trigger exactly one restore command.'
[[ "${recovery_commands[0]}" == *' app ai-gateway channel-worker translation-redis' ]] \
    || fail "failed activation omitted app network sidecars: ${recovery_commands[0]}"
[[ "${recovery_commands[1]}" == *' app ai-gateway channel-worker translation-redis' ]] \
    || fail "restore omitted app network sidecars: ${recovery_commands[1]}"

: > "$FAKE_DOCKER_LOG"
cat > "$FAKE_DOCKER_CONFIG" <<'JSON'
{"services":{"app":{"image":"synthetic.invalid/newshub:test"},"database":{"image":"synthetic.invalid/database:test"}}}
JSON
PATH="$TMP/bin:$PATH" "$SCRIPT" --execute \
    --project preview-test \
    --compose "$TMP/compose.yaml" \
    --root "$TMP/releases" \
    --wait-timeout 5
activation=$(grep ' up -d ' "$FAKE_DOCKER_LOG" | tail -1)
[[ "$activation" == *' app' && "$activation" != *' ai-gateway'* ]] \
    || fail "activation without sidecars did not recreate only app: $activation"

: > "$FAKE_DOCKER_LOG"
printf '{invalid json\n' > "$FAKE_DOCKER_CONFIG"
expect_failure 'could not identify services that share the app network namespace.' \
    env PATH="$TMP/bin:$PATH" "$SCRIPT" --execute \
        --project preview-test \
        --compose "$TMP/compose.yaml" \
        --root "$TMP/releases" \
        --wait-timeout 5
! grep -q ' up -d ' "$FAKE_DOCKER_LOG" \
    || fail 'invalid Compose JSON changed Docker state.'

printf 'test_local_frontend_preview: PASS\n'
