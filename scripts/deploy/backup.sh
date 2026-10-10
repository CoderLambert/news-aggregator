#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
EXECUTE=0
DB_PATH=""
OUTPUT=""
OUTPUT_DIR=""
FILENAME=""
MANIFEST=""
VOLUME=""
IMAGE=""
SHA=""
CONTAINER_ID=""
WORK_DIR=""

usage() {
    cat <<'EOF'
Usage:
  backup.sh [--execute] --db DB.sqlite3 --output SNAPSHOT.sqlite3 --manifest release.json
  backup.sh [--execute] --volume VOLUME --image IMAGE --sha 40-HEX-SHA \
      --filename NAME.sqlite3 --output-dir DIR --manifest release.json

The default is a dry run. Volume snapshots use SQLite's online backup API from a read-only mount.
EOF
}

fail() {
    printf 'backup: %s\n' "$1" >&2
    exit 2
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n "$CONTAINER_ID" ]]; then
        docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        case "$WORK_DIR" in
            "${OUTPUT_DIR:-/}/".newshub-backup.*) rm -rf -- "$WORK_DIR" ;;
            *) printf 'backup: refused to remove unexpected temporary directory.\n' >&2; status=1 ;;
        esac
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --db) (($# >= 2)) || fail '--db requires a value.'; DB_PATH=$2; shift 2 ;;
        --output) (($# >= 2)) || fail '--output requires a value.'; OUTPUT=$2; shift 2 ;;
        --output-dir) (($# >= 2)) || fail '--output-dir requires a value.'; OUTPUT_DIR=$2; shift 2 ;;
        --filename) (($# >= 2)) || fail '--filename requires a value.'; FILENAME=$2; shift 2 ;;
        --manifest) (($# >= 2)) || fail '--manifest requires a value.'; MANIFEST=$2; shift 2 ;;
        --volume) (($# >= 2)) || fail '--volume requires a value.'; VOLUME=$2; shift 2 ;;
        --image) (($# >= 2)) || fail '--image requires a value.'; IMAGE=$2; shift 2 ;;
        --sha) (($# >= 2)) || fail '--sha requires a value.'; SHA=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[[ -n "$MANIFEST" ]] || fail '--manifest is required.'
if [[ -n "$DB_PATH" ]]; then
    [[ -z "$VOLUME$IMAGE$SHA$FILENAME$OUTPUT_DIR" && -n "$OUTPUT" ]] \
        || fail 'direct mode requires only --db, --output, and --manifest.'
    [[ -f "$DB_PATH" && ! -L "$DB_PATH" ]] || fail '--db must be an existing regular database file.'
    [[ "$OUTPUT" == /* ]] || fail '--output must be an absolute path.'
    DESTINATION="$OUTPUT"
    DESTINATION_DIR="$(dirname -- "$DESTINATION")"
    [[ -d "$DESTINATION_DIR" && ! -L "$DESTINATION_DIR" ]] || fail 'output parent must be an existing real directory.'
else
    [[ -z "$OUTPUT" && -n "$VOLUME" && -n "$IMAGE" && -n "$SHA" && -n "$FILENAME" && -n "$OUTPUT_DIR" ]] \
        || fail 'volume mode requires --volume, --image, --sha, --filename, and --output-dir.'
    [[ "$VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail '--volume is invalid.'
    [[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must be exactly 40 hexadecimal characters.'
    SHA="${SHA,,}"
    [[ "$FILENAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.sqlite3$ && "$FILENAME" != *..* ]] \
        || fail '--filename must be a safe .sqlite3 basename.'
    [[ "$OUTPUT_DIR" == /* && -d "$OUTPUT_DIR" && ! -L "$OUTPUT_DIR" ]] \
        || fail '--output-dir must be an existing absolute real directory.'
    DESTINATION="$OUTPUT_DIR/$FILENAME"
    DESTINATION_DIR="$OUTPUT_DIR"
fi

[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || fail '--manifest must be an existing regular file.'
command -v python3 >/dev/null 2>&1 || fail 'python3 is unavailable.'
python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" >/dev/null \
    || fail 'release manifest is invalid.'
SIDECAR="$DESTINATION.manifest.json"
[[ ! -e "$DESTINATION" && ! -L "$DESTINATION" && ! -e "$SIDECAR" && ! -L "$SIDECAR" ]] \
    || fail 'snapshot output or manifest already exists; refusing to overwrite.'

if ((!EXECUTE)); then
    if [[ -n "$DB_PATH" ]]; then
        printf 'Dry run only: would create a mode-0600 SQLite online backup at the requested output; no database or filesystem changes.\n'
    else
        printf 'Dry run only: would read volume %s through a network-none helper and publish a mode-0600 snapshot; no Docker or filesystem changes.\n' "$VOLUME"
    fi
    exit 0
fi

if [[ -n "$DB_PATH" ]]; then
    python3 "$SCRIPT_DIR/sqlite_snapshot.py" backup \
        --source "$DB_PATH" --output "$DESTINATION" --release-manifest "$MANIFEST"
    exit 0
fi

python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" --image "$IMAGE" --sha "$SHA" >/dev/null \
    || fail 'requested image did not match its production manifest.'
command -v docker >/dev/null 2>&1 || fail 'Docker CLI is unavailable.'
running="$(docker ps --quiet --filter "volume=$VOLUME")" \
    || fail 'could not check running containers attached to the backup volume.'
[[ -z "$running" ]] || fail 'backup volume is mounted by a running container; stop all writers first.'
WORK_DIR="$(mktemp -d "$OUTPUT_DIR/.newshub-backup.XXXXXX")"
chmod 700 "$WORK_DIR"
container_args=(
    docker create --pull=never --network none --user 10001:10001 --entrypoint python
    --mount "type=volume,source=$VOLUME,target=/source,readonly"
    --mount "type=bind,source=$SCRIPT_DIR/sqlite_snapshot.py,target=/tmp/sqlite_snapshot.py,readonly"
    "$IMAGE" -c 'import time; time.sleep(300)'
)
CONTAINER_ID="$("${container_args[@]}")" || fail 'could not create the isolated backup helper.'
[[ -n "$CONTAINER_ID" ]] || fail 'backup helper did not return a container ID.'
docker start "$CONTAINER_ID" >/dev/null || fail 'could not start the isolated backup helper.'
docker cp "$MANIFEST" "$CONTAINER_ID:/tmp/release-manifest.json" >/dev/null \
    || fail 'could not stage the release manifest in the isolated helper.'
prepare_code='import os,sys; [(os.chown(path,10001,10001), os.chmod(path,0o600)) for path in sys.argv[1:]]'
docker exec --user 0:0 "$CONTAINER_ID" python -c "$prepare_code" /tmp/release-manifest.json \
    || fail 'could not prepare the private release manifest in the isolated helper.'
docker exec --user 10001:10001 "$CONTAINER_ID" python /tmp/sqlite_snapshot.py backup \
    --source /source/db.sqlite3 --output /tmp/snapshot.sqlite3 \
    --release-manifest /tmp/release-manifest.json \
    || fail 'SQLite volume backup helper failed.'
docker cp "$CONTAINER_ID:/tmp/snapshot.sqlite3" "$WORK_DIR/$FILENAME" >/dev/null \
    || fail 'could not copy the isolated SQLite snapshot.'
docker cp "$CONTAINER_ID:/tmp/snapshot.sqlite3.manifest.json" "$WORK_DIR/$FILENAME.manifest.json" >/dev/null \
    || fail 'could not copy the isolated snapshot manifest.'
python3 "$SCRIPT_DIR/sqlite_snapshot.py" validate \
    --database "$WORK_DIR/$FILENAME" --release-manifest "$MANIFEST" >/dev/null \
    || fail 'copied volume snapshot failed host-side validation.'
chmod 600 "$WORK_DIR/$FILENAME" "$WORK_DIR/$FILENAME.manifest.json"
ln -- "$WORK_DIR/$FILENAME" "$DESTINATION" || fail 'snapshot output appeared concurrently; refusing to overwrite.'
if ! ln -- "$WORK_DIR/$FILENAME.manifest.json" "$SIDECAR"; then
    rm -f -- "$DESTINATION"
    fail 'snapshot manifest output appeared concurrently; refused partial publication.'
fi
printf 'PASS: a consistent SQLite snapshot was created; database and manifest are mode 0600.\n'
