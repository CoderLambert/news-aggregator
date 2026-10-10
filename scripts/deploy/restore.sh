#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
EXECUTE=0
TARGET=""
SNAPSHOT=""
MANIFEST=""
PRIOR_BACKUP=""
VOLUME=""
IMAGE=""
SHA=""
REPLACE=0
WRITERS_STOPPED=0
CONTAINER_ID=""

usage() {
    cat <<'EOF'
Usage:
  restore.sh [--execute] --snapshot SNAPSHOT.sqlite3 --target DB.sqlite3 --manifest release.json
              [--replace --writers-stopped --prior-backup OLD-SNAPSHOT.sqlite3]
  restore.sh [--execute] --snapshot SNAPSHOT.sqlite3 --volume VOLUME --image IMAGE
              --sha 40-HEX-SHA --manifest release.json
              [--replace --writers-stopped --prior-backup OLD-SNAPSHOT.sqlite3]

Restores only from a validated SQLite online-backup artifact. Existing targets require
an explicit stopped-writer declaration and a valid old-data backup artifact.
EOF
}

fail() {
    printf 'restore: %s\n' "$1" >&2
    exit 2
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n "$CONTAINER_ID" ]]; then
        docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --target) (($# >= 2)) || fail '--target requires a value.'; TARGET=$2; shift 2 ;;
        --snapshot) (($# >= 2)) || fail '--snapshot requires a value.'; SNAPSHOT=$2; shift 2 ;;
        --manifest) (($# >= 2)) || fail '--manifest requires a value.'; MANIFEST=$2; shift 2 ;;
        --prior-backup) (($# >= 2)) || fail '--prior-backup requires a value.'; PRIOR_BACKUP=$2; shift 2 ;;
        --volume) (($# >= 2)) || fail '--volume requires a value.'; VOLUME=$2; shift 2 ;;
        --image) (($# >= 2)) || fail '--image requires a value.'; IMAGE=$2; shift 2 ;;
        --sha) (($# >= 2)) || fail '--sha requires a value.'; SHA=$2; shift 2 ;;
        --replace) REPLACE=1; shift ;;
        --writers-stopped) WRITERS_STOPPED=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[[ -n "$SNAPSHOT" && -n "$MANIFEST" ]] || fail '--snapshot and --manifest are required.'
[[ -f "$SNAPSHOT" && ! -L "$SNAPSHOT" ]] || fail '--snapshot must be an existing regular file.'
[[ -f "$SNAPSHOT.manifest.json" && ! -L "$SNAPSHOT.manifest.json" ]] \
    || fail 'snapshot manifest sidecar is missing or invalid.'
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || fail '--manifest must be an existing regular file.'
if ((REPLACE != WRITERS_STOPPED)); then
    fail '--replace and --writers-stopped must be provided together.'
fi
if [[ -n "$VOLUME" ]]; then
    [[ -z "$TARGET" && -n "$IMAGE" && -n "$SHA" ]] || fail 'volume mode requires --volume, --image, and --sha only.'
    [[ "$VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail '--volume is invalid.'
    [[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must be exactly 40 hexadecimal characters.'
    SHA="${SHA,,}"
else
    [[ -n "$TARGET" && -z "$IMAGE$SHA" ]] || fail 'direct mode requires --target and must not include image arguments.'
    [[ "$TARGET" == /* ]] || fail '--target must be an absolute path.'
    [[ -d "$(dirname -- "$TARGET")" && ! -L "$(dirname -- "$TARGET")" ]] \
        || fail 'target parent must be an existing real directory.'
fi
if [[ -n "$PRIOR_BACKUP" ]]; then
    [[ -f "$PRIOR_BACKUP" && ! -L "$PRIOR_BACKUP" && -f "$PRIOR_BACKUP.manifest.json" && ! -L "$PRIOR_BACKUP.manifest.json" ]] \
        || fail '--prior-backup must be a complete regular snapshot artifact.'
fi
if ((REPLACE)) && [[ -z "$PRIOR_BACKUP" ]]; then
    fail '--replace requires --prior-backup.'
fi

command -v python3 >/dev/null 2>&1 || fail 'python3 is unavailable.'
python3 "$SCRIPT_DIR/sqlite_snapshot.py" validate --database "$SNAPSHOT" --release-manifest "$MANIFEST" >/dev/null \
    || fail 'snapshot failed SQLite, digest, schema, or release-manifest validation.'
if [[ -n "$PRIOR_BACKUP" ]]; then
    python3 "$SCRIPT_DIR/sqlite_snapshot.py" validate --database "$PRIOR_BACKUP" >/dev/null \
        || fail 'prior backup failed SQLite or manifest validation.'
fi

if ((!EXECUTE)); then
    if [[ -n "$VOLUME" ]]; then
        printf 'Dry run only: would verify no running container mounts volume %s and restore from the validated snapshot; no Docker or filesystem changes.\n' "$VOLUME"
    else
        printf 'Dry run only: would restore the validated snapshot to the requested database path; no database or filesystem changes.\n'
    fi
    exit 0
fi

restore_args=(restore --source "$SNAPSHOT" --release-manifest "$MANIFEST")
if ((REPLACE)); then
    restore_args+=(--replace --writers-stopped --prior-backup "$PRIOR_BACKUP")
fi
if [[ -z "$VOLUME" ]]; then
    python3 "$SCRIPT_DIR/sqlite_snapshot.py" "${restore_args[@]}" --target "$TARGET"
    exit 0
fi

python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" --image "$IMAGE" --sha "$SHA" >/dev/null \
    || fail 'requested helper image did not match its production manifest.'
command -v docker >/dev/null 2>&1 || fail 'Docker CLI is unavailable.'
running="$(docker ps --quiet --filter "volume=$VOLUME")" \
    || fail 'could not check running containers attached to the restore volume.'
[[ -z "$running" ]] || fail 'restore volume is mounted by a running container; stop all writers first.'

CONTAINER_ID="$(docker create --pull=never --network none --entrypoint python \
    --mount "type=volume,source=$VOLUME,target=/source" \
    --mount "type=bind,source=$SCRIPT_DIR/sqlite_snapshot.py,target=/tmp/sqlite_snapshot.py,readonly" \
    "$IMAGE" -c 'import time; exec("while True: time.sleep(3600)")')" \
    || fail 'could not create the isolated restore helper.'
[[ -n "$CONTAINER_ID" ]] || fail 'restore helper did not return a container ID.'
docker start "$CONTAINER_ID" >/dev/null || fail 'could not start the isolated restore helper.'
docker cp "$SNAPSHOT" "$CONTAINER_ID:/tmp/snapshot.sqlite3" >/dev/null \
    || fail 'could not stage the supplied snapshot in the isolated helper.'
docker cp "$SNAPSHOT.manifest.json" "$CONTAINER_ID:/tmp/snapshot.sqlite3.manifest.json" >/dev/null \
    || fail 'could not stage the snapshot manifest in the isolated helper.'
docker cp "$MANIFEST" "$CONTAINER_ID:/tmp/release-manifest.json" >/dev/null \
    || fail 'could not stage the release manifest in the isolated helper.'
if ((REPLACE)); then
    docker cp "$PRIOR_BACKUP" "$CONTAINER_ID:/tmp/prior.sqlite3" >/dev/null \
        || fail 'could not stage the prior backup in the isolated helper.'
    docker cp "$PRIOR_BACKUP.manifest.json" "$CONTAINER_ID:/tmp/prior.sqlite3.manifest.json" >/dev/null \
        || fail 'could not stage the prior backup manifest in the isolated helper.'
fi
chmod_code='import os,sys; [os.chmod(path, 0o644) for path in sys.argv[1:]]'
chmod_paths=(/tmp/snapshot.sqlite3 /tmp/snapshot.sqlite3.manifest.json /tmp/release-manifest.json)
if ((REPLACE)); then
    chmod_paths+=(/tmp/prior.sqlite3 /tmp/prior.sqlite3.manifest.json)
fi
docker exec --user 0:0 "$CONTAINER_ID" python -c "$chmod_code" "${chmod_paths[@]}" \
    || fail 'could not make staged read-only artifacts readable to the non-root helper.'
container_restore_args=(restore --source /tmp/snapshot.sqlite3 --target /source/db.sqlite3 --release-manifest /tmp/release-manifest.json)
if ((REPLACE)); then
    container_restore_args+=(--replace --writers-stopped --prior-backup /tmp/prior.sqlite3)
fi
docker exec --user 10001:10001 "$CONTAINER_ID" python /tmp/sqlite_snapshot.py "${container_restore_args[@]}" \
    || fail 'volume restore failed validation or migration lock checks.'
printf 'PASS: the validated snapshot was restored to the stopped volume using the non-root application UID.\n'
