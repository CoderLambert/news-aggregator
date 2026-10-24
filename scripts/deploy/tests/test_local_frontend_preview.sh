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
        fail "command unexpectedly succeeded: $*"
    fi
    [[ "$output" == *"$expected"* ]] || fail "missing failure text '$expected': $output"
}

cat > "$TMP/compose.yaml" <<'YAML'
services:
  app:
    image: synthetic.invalid/newshub:test
YAML

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

printf 'test_local_frontend_preview: PASS\n'
