#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
SCRIPT="$PROJECT_ROOT/scripts/deploy/export-static.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/newshub-export-tests.XXXXXX")"
MOCK_BIN="$TEST_ROOT/bin"
DOCKER_LOG="$TEST_ROOT/docker.log"
mkdir -p "$MOCK_BIN"
touch "$DOCKER_LOG"

cleanup() {
    rm -rf -- "$TEST_ROOT"
}
trap cleanup EXIT

cat > "$MOCK_BIN/docker" <<'MOCK_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "$DOCKER_LOG"
case "${1:-}" in
    image)
        [[ "${2:-}" == inspect ]] || exit 90
        printf '%s\n' "$MOCK_REVISION"
        ;;
    create)
        [[ "${2:-}" == --network && "${3:-}" == none ]] || exit 91
        printf 'mock-export-container\n'
        ;;
    cp)
        [[ "${MOCK_CP_FAIL:-0}" == 0 ]] || exit 44
        destination="${@: -1}"
        mkdir -p "$destination"
        cp -a "$MOCK_DIST/." "$destination"
        ;;
    rm)
        [[ "${2:-}" == mock-export-container ]] || exit 92
        ;;
    *)
        exit 93
        ;;
esac
MOCK_DOCKER
chmod +x "$MOCK_BIN/docker"

export PATH="$MOCK_BIN:$PATH"
export DOCKER_LOG

assert() {
    if ! "$@"; then
        printf 'assertion failed: %s\n' "$*" >&2
        exit 1
    fi
}

expect_failure() {
    if "$@" >"$TEST_ROOT/command.out" 2>&1; then
        printf 'expected command to fail: %s\n' "$*" >&2
        cat "$TEST_ROOT/command.out" >&2
        exit 1
    fi
}

assert_current() {
    local root=$1
    local sha=$2
    assert test "$(readlink "$root/current")" = "releases/$sha"
}

SHA_OLD=1111111111111111111111111111111111111111
SHA_PREVIOUS=2222222222222222222222222222222222222222
SHA_NEW=abcdef0123456789abcdef0123456789abcdef01
SHA_MISMATCH=3333333333333333333333333333333333333333
SHA_SECOND=4444444444444444444444444444444444444444

MOCK_REVISION=$SHA_NEW
export MOCK_REVISION

"$SCRIPT" >"$TEST_ROOT/dry-run.out"
assert test ! -s "$DOCKER_LOG"
assert test ! -e "$TEST_ROOT/releases"

"$SCRIPT" --image local/test --sha "$SHA_NEW" --root "$TEST_ROOT/dry-root" >"$TEST_ROOT/dry-run-args.out"
assert test ! -s "$DOCKER_LOG"
assert test ! -e "$TEST_ROOT/dry-root"

expect_failure "$SCRIPT" --execute --image local/test --sha invalid --root "$TEST_ROOT/bad-sha"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root relative/path
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root /
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$PROJECT_ROOT"
ln -s "$PROJECT_ROOT" "$TEST_ROOT/source-tree-alias"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$TEST_ROOT/source-tree-alias"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW"
assert test ! -s "$DOCKER_LOG"

MOCK_REVISION=$SHA_MISMATCH
export MOCK_REVISION
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$TEST_ROOT/mismatch-root"
assert test ! -e "$TEST_ROOT/mismatch-root"
assert test "$(grep -c '^create ' "$DOCKER_LOG" || true)" -eq 0

prepare_old_root() {
    local root=$1
    mkdir -p "$root/releases/$SHA_OLD" "$root/releases/$SHA_PREVIOUS" "$root/assets"
    printf 'old index\n' > "$root/releases/$SHA_OLD/index.html"
    printf 'previous index\n' > "$root/releases/$SHA_PREVIOUS/index.html"
    printf 'older content\n' > "$root/assets/old.hash.js"
    ln -s "releases/$SHA_OLD" "$root/current"
    ln -s "releases/$SHA_PREVIOUS" "$root/previous"
}

MOCK_REVISION=$SHA_NEW
export MOCK_REVISION

MISSING_INDEX_DIST="$TEST_ROOT/missing-index-dist"
mkdir -p "$MISSING_INDEX_DIST/assets"
printf 'asset\n' > "$MISSING_INDEX_DIST/assets/app.hash.js"
export MOCK_DIST="$MISSING_INDEX_DIST"
MISSING_INDEX_ROOT="$TEST_ROOT/missing-index-root"
prepare_old_root "$MISSING_INDEX_ROOT"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$MISSING_INDEX_ROOT"
assert_current "$MISSING_INDEX_ROOT" "$SHA_OLD"
assert test ! -e "$MISSING_INDEX_ROOT/releases/$SHA_NEW"

MISSING_ASSETS_DIST="$TEST_ROOT/missing-assets-dist"
mkdir -p "$MISSING_ASSETS_DIST"
printf '<html></html>\n' > "$MISSING_ASSETS_DIST/index.html"
export MOCK_DIST="$MISSING_ASSETS_DIST"
MISSING_ASSETS_ROOT="$TEST_ROOT/missing-assets-root"
prepare_old_root "$MISSING_ASSETS_ROOT"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$MISSING_ASSETS_ROOT"
assert_current "$MISSING_ASSETS_ROOT" "$SHA_OLD"
assert test ! -e "$MISSING_ASSETS_ROOT/releases/$SHA_NEW"

CONFLICT_DIST="$TEST_ROOT/conflict-dist"
mkdir -p "$CONFLICT_DIST/assets"
printf '<html><script src="/assets/app.hash.js"></script></html>\n' > "$CONFLICT_DIST/index.html"
printf 'new content\n' > "$CONFLICT_DIST/assets/app.hash.js"
export MOCK_DIST="$CONFLICT_DIST"
CONFLICT_ROOT="$TEST_ROOT/conflict-root"
prepare_old_root "$CONFLICT_ROOT"
printf 'different old content\n' > "$CONFLICT_ROOT/assets/app.hash.js"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$CONFLICT_ROOT"
assert_current "$CONFLICT_ROOT" "$SHA_OLD"
assert test "$(cat "$CONFLICT_ROOT/assets/app.hash.js")" = 'different old content'
assert test ! -e "$CONFLICT_ROOT/releases/$SHA_NEW"

COPY_FAIL_DIST="$TEST_ROOT/copy-failure-dist"
mkdir -p "$COPY_FAIL_DIST/assets"
printf '<html></html>\n' > "$COPY_FAIL_DIST/index.html"
printf 'asset\n' > "$COPY_FAIL_DIST/assets/app.hash.js"
export MOCK_DIST="$COPY_FAIL_DIST"
export MOCK_CP_FAIL=1
COPY_FAIL_ROOT="$TEST_ROOT/copy-failure-root"
prepare_old_root "$COPY_FAIL_ROOT"
expect_failure "$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$COPY_FAIL_ROOT"
assert_current "$COPY_FAIL_ROOT" "$SHA_OLD"
assert test ! -e "$COPY_FAIL_ROOT/releases/$SHA_NEW"
assert grep -q '^rm mock-export-container$' "$DOCKER_LOG"
unset MOCK_CP_FAIL

SUCCESS_DIST="$TEST_ROOT/success-dist"
umask 077
mkdir -p "$SUCCESS_DIST/assets"
printf '<html><script src="/assets/app.hash.js"></script></html>\n' > "$SUCCESS_DIST/index.html"
printf '<svg></svg>\n' > "$SUCCESS_DIST/favicon.svg"
printf 'new asset\n' > "$SUCCESS_DIST/assets/app.hash.js"
printf 'chunk\n' > "$SUCCESS_DIST/assets/chunk.hash.js"
export MOCK_DIST="$SUCCESS_DIST"
SUCCESS_ROOT="$TEST_ROOT/success-root"
prepare_old_root "$SUCCESS_ROOT"
"$SCRIPT" --execute --image local/test --sha "$SHA_NEW" --root "$SUCCESS_ROOT" >"$TEST_ROOT/success.out"
assert_current "$SUCCESS_ROOT" "$SHA_NEW"
assert test "$(readlink "$SUCCESS_ROOT/previous")" = "releases/$SHA_OLD"
assert test -d "$SUCCESS_ROOT/releases/$SHA_OLD"
assert test -d "$SUCCESS_ROOT/releases/$SHA_PREVIOUS"
assert test -f "$SUCCESS_ROOT/releases/$SHA_NEW/index.html"
assert test -d "$SUCCESS_ROOT/releases/$SHA_NEW/assets"
assert test ! -L "$SUCCESS_ROOT/releases/$SHA_NEW/assets"
assert test "$(cat "$SUCCESS_ROOT/assets/app.hash.js")" = 'new asset'
assert test "$(cat "$SUCCESS_ROOT/assets/old.hash.js")" = 'older content'
assert test "$SUCCESS_ROOT/assets/app.hash.js" -ef "$SUCCESS_ROOT/releases/$SHA_NEW/assets/app.hash.js"
assert test "$(stat -c '%a' "$SUCCESS_ROOT")" = 755
assert test "$(stat -c '%a' "$SUCCESS_ROOT/releases")" = 755
assert test "$(stat -c '%a' "$SUCCESS_ROOT/assets")" = 755
assert test "$(stat -c '%a' "$SUCCESS_ROOT/releases/$SHA_NEW")" = 755
assert test "$(stat -c '%a' "$SUCCESS_ROOT/releases/$SHA_NEW/assets")" = 755
while IFS= read -r -d '' public_directory; do
    assert test "$(stat -c '%a' "$public_directory")" = 755
done < <(find "$SUCCESS_ROOT/releases/$SHA_NEW" -type d -print0)
while IFS= read -r -d '' public_file; do
    assert test "$(stat -c '%a' "$public_file")" = 644
done < <(find "$SUCCESS_ROOT/releases/$SHA_NEW" -type f -print0)
assert grep -q '^create --network none local/test$' "$DOCKER_LOG"
assert grep -q '^cp mock-export-container:/app/frontend/dist/\.' "$DOCKER_LOG"
assert grep -q '^rm mock-export-container$' "$DOCKER_LOG"
assert test "$(grep -c '^start ' "$DOCKER_LOG" || true)" -eq 0

FIRST_RELEASE_HASH="$(PYTHONPATH="$PROJECT_ROOT" python3 - "$SUCCESS_ROOT/releases/$SHA_NEW" <<'PY'
import sys
from pathlib import Path
from scripts.deploy.release_manifest import sha256_exported_release
print(sha256_exported_release(Path(sys.argv[1])))
PY
)"
PYTHONPATH="$PROJECT_ROOT" python3 - "$SUCCESS_ROOT/releases/$SHA_NEW" "$SUCCESS_DIST" <<'PY'
import sys
from pathlib import Path
from scripts.deploy.release_manifest import sha256_exported_release, sha256_tree
release, dist = map(Path, sys.argv[1:])
assert sha256_exported_release(release) == sha256_tree(dist)
PY

SECOND_DIST="$TEST_ROOT/second-dist"
mkdir -p "$SECOND_DIST/assets"
printf '<html><script src="/assets/app.hash.js"></script><script src="/assets/chunk-v2.hash.js"></script></html>\n' > "$SECOND_DIST/index.html"
printf 'new asset\n' > "$SECOND_DIST/assets/app.hash.js"
printf 'second chunk\n' > "$SECOND_DIST/assets/chunk-v2.hash.js"
MOCK_DIST="$SECOND_DIST"
MOCK_REVISION="$SHA_SECOND"
export MOCK_DIST MOCK_REVISION
"$SCRIPT" --execute --image local/test --sha "$SHA_SECOND" --root "$SUCCESS_ROOT" >"$TEST_ROOT/second.out"
assert_current "$SUCCESS_ROOT" "$SHA_SECOND"
assert test "$(readlink "$SUCCESS_ROOT/previous")" = "releases/$SHA_NEW"
assert test -f "$SUCCESS_ROOT/assets/chunk.hash.js"
assert test "$(cat "$SUCCESS_ROOT/assets/chunk.hash.js")" = 'chunk'
assert test ! -e "$SUCCESS_ROOT/releases/$SHA_SECOND/assets/chunk.hash.js"
assert test "$SUCCESS_ROOT/assets/chunk-v2.hash.js" -ef "$SUCCESS_ROOT/releases/$SHA_SECOND/assets/chunk-v2.hash.js"
assert test "$(stat -c '%a' "$SUCCESS_ROOT/releases/$SHA_SECOND")" = 755
assert test "$(stat -c '%a' "$SUCCESS_ROOT/releases/$SHA_SECOND/assets")" = 755
SECOND_RELEASE_HASH="$(PYTHONPATH="$PROJECT_ROOT" python3 - "$SUCCESS_ROOT/releases/$SHA_SECOND" <<'PY'
import sys
from pathlib import Path
from scripts.deploy.release_manifest import sha256_exported_release
print(sha256_exported_release(Path(sys.argv[1])))
PY
)"
PYTHONPATH="$PROJECT_ROOT" python3 - "$SUCCESS_ROOT/releases/$SHA_NEW" "$SUCCESS_DIST" "$SUCCESS_ROOT/releases/$SHA_SECOND" "$SECOND_DIST" "$FIRST_RELEASE_HASH" "$SECOND_RELEASE_HASH" <<'PY'
import sys
from pathlib import Path
from scripts.deploy.release_manifest import sha256_exported_release, sha256_tree
first, first_dist, second, second_dist = map(Path, sys.argv[1:5])
first_expected, second_expected = sys.argv[5:]
assert sha256_exported_release(first) == sha256_tree(first_dist) == first_expected
assert sha256_exported_release(second) == sha256_tree(second_dist) == second_expected
PY

printf 'export-static tests passed\n'
