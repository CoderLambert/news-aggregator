#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
COMPOSE_FILE="$PROJECT_ROOT/compose.prod.yaml"
EXECUTE=0
FRESH=0
ENV_FILE=""
PROJECT=""
SHA=""
IMAGE=""
ROOT=""
MANIFEST=""
CURRENT_MANIFEST=""
BACKUP_OUTPUT=""
DB_VOLUME=""
WINDOW_STARTED=0
COMPLETE=0
STATIC_SWITCHED=0
OLD_CURRENT_TARGET=""

usage() {
    cat <<'EOF'
Usage:
  deploy.sh [--execute] --env-file ABSOLUTE-FILE --project NAME --sha 40-HEX-SHA \
      --image IMAGE --root ABSOLUTE-STATIC-ROOT --manifest TARGET-MANIFEST \
      --db-volume PROJECT_db-data --current-manifest CURRENT-MANIFEST \
      --backup-output ABSOLUTE-SNAPSHOT.sqlite3
  deploy.sh [--execute] --fresh --env-file ABSOLUTE-FILE --project NAME \
      --sha 40-HEX-SHA --image IMAGE --root ABSOLUTE-STATIC-ROOT \
      --manifest TARGET-MANIFEST --db-volume PROJECT_db-data

Without --execute this validates local inputs and prints the maintenance-window plan.
An existing database is stopped, backed up against its current image manifest, migrated
once, then started and health-checked before the static current link is switched.
EOF
}

fail() {
    printf 'deploy: %s\n' "$1" >&2
    exit 2
}

restore_old_static_if_needed() {
    ((STATIC_SWITCHED)) || return 0
    if [[ -n "$OLD_CURRENT_TARGET" && -L "$ROOT/current" ]]; then
        local target
        target="$(readlink -- "$ROOT/current")" || return 1
        if [[ "$target" == "releases/$SHA" ]]; then
            local temporary="$ROOT/.current.restore.$$"
            [[ ! -e "$temporary" && ! -L "$temporary" ]] || return 1
            ln -s -- "$OLD_CURRENT_TARGET" "$temporary" || return 1
            mv -Tf -- "$temporary" "$ROOT/current" || return 1
        fi
    fi
}

cleanup() {
    local status=$?
    trap - EXIT
    if ((WINDOW_STARTED && !COMPLETE)); then
        if ! compose_call stop --timeout 45 crawler indexer app >/dev/null 2>&1; then
            printf 'deploy: failed to confirm fail-closed stop for this Compose project.\n' >&2
        fi
        if ! restore_old_static_if_needed; then
            printf 'deploy: failed to restore the prior static current link after a rejected export.\n' >&2
            status=1
        fi
        printf 'deploy: this project remains stopped after failure; no old image was restarted.\n' >&2
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --fresh) FRESH=1; shift ;;
        --env-file) (($# >= 2)) || fail '--env-file requires a value.'; ENV_FILE=$2; shift 2 ;;
        --project) (($# >= 2)) || fail '--project requires a value.'; PROJECT=$2; shift 2 ;;
        --sha) (($# >= 2)) || fail '--sha requires a value.'; SHA=$2; shift 2 ;;
        --image) (($# >= 2)) || fail '--image requires a value.'; IMAGE=$2; shift 2 ;;
        --root) (($# >= 2)) || fail '--root requires a value.'; ROOT=$2; shift 2 ;;
        --manifest) (($# >= 2)) || fail '--manifest requires a value.'; MANIFEST=$2; shift 2 ;;
        --current-manifest) (($# >= 2)) || fail '--current-manifest requires a value.'; CURRENT_MANIFEST=$2; shift 2 ;;
        --backup-output) (($# >= 2)) || fail '--backup-output requires a value.'; BACKUP_OUTPUT=$2; shift 2 ;;
        --db-volume) (($# >= 2)) || fail '--db-volume requires a value.'; DB_VOLUME=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[[ "$ENV_FILE" == /* && -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] \
    || fail '--env-file must be an absolute path to a regular file.'
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || fail '--project must be a lowercase Compose project name.'
[[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must contain exactly 40 hexadecimal characters.'
SHA="${SHA,,}"
[[ -n "$IMAGE" ]] || fail '--image is required.'
[[ "$ROOT" == /* && "$ROOT" != / ]] || fail '--root must be an absolute non-root path.'
ROOT="$(realpath -m -- "$ROOT")"
[[ "$ROOT" != / && "$ROOT" != "$PROJECT_ROOT" && "$ROOT" != "$PROJECT_ROOT/"* ]] \
    || fail '--root must resolve outside the source tree and must not be /. '
[[ ! -L "$ROOT" ]] || fail '--root must not be a symlink.'
[[ "$DB_VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail '--db-volume is invalid.'
[[ "$DB_VOLUME" == "${PROJECT}_db-data" ]] || fail '--db-volume must be the explicit project db-data volume.'
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || fail '--manifest must be a regular target release manifest.'
python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" >/dev/null \
    || fail 'target release manifest is invalid.'
TARGET_SHA="$(python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["release_sha"])
PY
)"
[[ "$TARGET_SHA" == "$SHA" ]] || fail 'target manifest SHA does not match --sha.'

if ((FRESH)); then
    [[ -z "$CURRENT_MANIFEST$BACKUP_OUTPUT" ]] \
        || fail '--fresh cannot include --current-manifest or --backup-output.'
else
    [[ -f "$CURRENT_MANIFEST" && ! -L "$CURRENT_MANIFEST" ]] \
        || fail 'existing database deployments require --current-manifest.'
    [[ "$BACKUP_OUTPUT" == /* && "$BACKUP_OUTPUT" == *.sqlite3 ]] \
        || fail '--backup-output must be an absolute .sqlite3 artifact path.'
    [[ "$BACKUP_OUTPUT" != "$PROJECT_ROOT"/* && "$BACKUP_OUTPUT" != "$ROOT"/* ]] \
        || fail '--backup-output must be outside the source tree and static root.'
    BACKUP_DIR="$(dirname -- "$BACKUP_OUTPUT")"
    [[ -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] \
        || fail '--backup-output parent must be an existing real directory.'
    [[ ! -e "$BACKUP_OUTPUT" && ! -L "$BACKUP_OUTPUT" \
        && ! -e "$BACKUP_OUTPUT.manifest.json" && ! -L "$BACKUP_OUTPUT.manifest.json" ]] \
        || fail 'backup output or sidecar already exists; refusing to overwrite.'
    python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$CURRENT_MANIFEST" >/dev/null \
        || fail 'current release manifest is invalid.'
    CURRENT_SHA="$(python3 - "$CURRENT_MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["release_sha"])
PY
)"
    CURRENT_IMAGE="$(python3 - "$CURRENT_MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["image"])
PY
)"
    [[ "$CURRENT_SHA" != "$SHA" ]] || fail 'target SHA is already the current release.'
fi

COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
compose_call() {
    NEWSHUB_IMAGE="$IMAGE" NEWSHUB_ENV_FILE="$ENV_FILE" "${COMPOSE[@]}" "$@"
}

if ((!EXECUTE)); then
    if ((FRESH)); then
        printf 'Dry run only: would verify project %s has no app/workers and an absent database, migrate %s once, health-check app/workers, then export static to %s; no Docker or filesystem changes.\n' \
            "$PROJECT" "$IMAGE" "$ROOT"
    else
        printf 'Dry run only: would verify the current app/volume/manifests, stop only project %s, create a new old-schema SQLite snapshot at %s, migrate %s once, health-check app/workers, then export static to %s; no Docker or filesystem changes.\n' \
            "$PROJECT" "$BACKUP_OUTPUT" "$IMAGE" "$ROOT"
    fi
    exit 0
fi

command -v docker >/dev/null 2>&1 || fail 'Docker CLI is unavailable.'
command -v python3 >/dev/null 2>&1 || fail 'python3 is unavailable.'
command -v realpath >/dev/null 2>&1 || fail 'realpath is unavailable.'
command -v sleep >/dev/null 2>&1 || fail 'sleep is unavailable.'
if [[ -n "${DOCKER_HOST:-}" && "$DOCKER_HOST" != unix://* && "$DOCKER_HOST" != npipe://* ]]; then
    fail 'remote DOCKER_HOST endpoints are not allowed.'
fi
docker_context="$(docker context show 2>/dev/null)" || fail 'could not read the selected Docker context.'
docker_endpoint="$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$docker_context" 2>/dev/null)" \
    || fail 'could not verify the selected Docker endpoint.'
[[ "$docker_endpoint" == unix://* || "$docker_endpoint" == npipe://* ]] \
    || fail 'remote Docker contexts are not allowed.'

python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" --image "$IMAGE" --sha "$SHA" >/dev/null \
    || fail 'target image revision/user did not match the target manifest.'
compose_call config --quiet || fail 'production Compose configuration is incomplete or invalid.'

if [[ -e "$ROOT" ]]; then
    [[ -d "$ROOT" && ! -L "$ROOT" ]] || fail '--root must be a real directory when it exists.'
fi
if ((FRESH)); then
    [[ ! -e "$ROOT/current" && ! -L "$ROOT/current" ]] \
        || fail '--fresh requires no existing current static release.'
    for service in app crawler indexer; do
        existing="$("${COMPOSE[@]}" ps --all --quiet "$service")" \
            || fail "could not inspect existing Compose service $service."
        [[ -z "$existing" ]] || fail "--fresh requires no existing $service container in this project."
    done
    volume_names="$(docker volume ls --format '{{.Name}}')" || fail 'could not list local Docker volumes.'
    volume_exists=0
    while IFS= read -r volume_name; do
        [[ "$volume_name" == "$DB_VOLUME" ]] && volume_exists=1
    done <<<"$volume_names"
    if ((volume_exists)); then
        present="$(docker run --rm --pull=never --network none --entrypoint python \
            --mount "type=volume,source=$DB_VOLUME,target=/probe,readonly" \
            "$IMAGE" -c 'import os; print("exists" if os.path.lexists("/probe/db.sqlite3") else "absent")')" \
            || fail 'could not verify the existing database volume.'
        [[ "$present" == absent ]] || fail '--fresh refuses an existing database file.'
    fi
else
    python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$CURRENT_MANIFEST" \
        --image "$CURRENT_IMAGE" --sha "$CURRENT_SHA" >/dev/null \
        || fail 'current image revision/user did not match the current manifest.'
    compose_call config --quiet || fail 'production Compose configuration is incomplete or invalid.'
    app_ids_raw="$("${COMPOSE[@]}" ps --all --quiet app)" || fail 'could not inspect the current app container.'
    mapfile -t app_ids <<<"$app_ids_raw"
    app_ids=("${app_ids[@]/#/}")
    filtered_ids=()
    for item in "${app_ids[@]}"; do [[ -n "$item" ]] && filtered_ids+=("$item"); done
    ((${#filtered_ids[@]} == 1)) || fail 'existing deployments require exactly one app container in the selected project.'
    APP_ID="${filtered_ids[0]}"
    app_status="$(docker inspect --format '{{.State.Status}}' "$APP_ID")" || fail 'could not inspect current app state.'
    [[ "$app_status" == running ]] || fail 'current app must be running before entering the maintenance window.'
    app_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$APP_ID")" \
        || fail 'could not inspect current app health.'
    [[ "$app_health" == healthy ]] || fail 'current app must be healthy before entering the maintenance window.'
    app_image="$(docker inspect --format '{{.Config.Image}}' "$APP_ID")" || fail 'could not inspect current app image.'
    [[ "$app_image" == "$CURRENT_IMAGE" ]] || fail 'current app image does not match --current-manifest.'
    app_revision="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$APP_ID")" \
        || fail 'could not inspect current app revision.'
    [[ "$app_revision" == "$CURRENT_SHA" ]] || fail 'current app revision does not match --current-manifest.'
    app_db_mount="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/newshub/db"}}{{.Type}}|{{.Name}}|{{.RW}}{{end}}{{end}}' "$APP_ID")" \
        || fail 'could not inspect current app database mount.'
    [[ "$app_db_mount" == "volume|$DB_VOLUME|true" ]] \
        || fail 'current app does not mount the explicitly requested database volume read/write.'
    [[ -L "$ROOT/current" ]] || fail 'existing deployments require a current static symlink.'
    OLD_CURRENT_TARGET="$(readlink -- "$ROOT/current")" || fail 'could not read current static release.'
    [[ "$OLD_CURRENT_TARGET" == "releases/$CURRENT_SHA" ]] \
        || fail 'current static release does not match --current-manifest.'
    python3 "$SCRIPT_DIR/release_manifest.py" validate-static --release "$ROOT/$OLD_CURRENT_TARGET" \
        --expected-sha "$(python3 - "$CURRENT_MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["static_sha"])
PY
)" >/dev/null || fail 'current static release does not match --current-manifest.'
fi

WINDOW_STARTED=1
if ((FRESH)); then
    run_compose_migrate() {
        compose_call run --rm --no-deps migrate
    }
    run_compose_migrate || fail 'one-shot database migration failed; project remains stopped.'
else
    compose_call stop --timeout 45 crawler indexer app \
        || fail 'could not stop all project writers; project remains stopped.'
    running="$(docker ps --quiet --filter "volume=$DB_VOLUME")" \
        || fail 'could not verify that database volume writers stopped.'
    [[ -z "$running" ]] || fail 'database volume still has a running container; project remains stopped.'
    BACKUP_NAME="$(basename -- "$BACKUP_OUTPUT")"
    scripts_backup="$SCRIPT_DIR/backup.sh"
    bash "$scripts_backup" --execute --volume "$DB_VOLUME" --image "$CURRENT_IMAGE" \
        --sha "$CURRENT_SHA" --filename "$BACKUP_NAME" --output-dir "$BACKUP_DIR" \
        --manifest "$CURRENT_MANIFEST" || fail 'current-schema SQLite snapshot failed; project remains stopped.'
    python3 "$SCRIPT_DIR/sqlite_snapshot.py" validate --database "$BACKUP_OUTPUT" \
        --release-manifest "$CURRENT_MANIFEST" >/dev/null \
        || fail 'new current-schema SQLite snapshot failed independent validation; project remains stopped.'
    running="$(docker ps --quiet --filter "volume=$DB_VOLUME")" \
        || fail 'could not recheck database volume writers before migration.'
    [[ -z "$running" ]] || fail 'database volume acquired a running container before migration; project remains stopped.'
    compose_call run --rm --no-deps migrate \
        || fail 'one-shot database migration failed; project remains stopped.'
fi

compose_call up --no-deps --detach app || fail 'new app failed to start; project remains stopped.'
wait_healthy() {
    local service=$1
    local deadline=$((SECONDS + 300))
    local ids status health
    while ((SECONDS < deadline)); do
        ids="$("${COMPOSE[@]}" ps --all --quiet "$service")" || return 1
        mapfile -t ids <<<"$ids"
        local found=0 id
        for id in "${ids[@]}"; do
            [[ -n "$id" ]] || continue
            found=1
            status="$(docker inspect --format '{{.State.Status}}' "$id")" || return 1
            [[ "$status" != exited && "$status" != dead ]] || return 1
            health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$id")" || return 1
            [[ "$health" == healthy ]] && return 0
        done
        ((found)) || return 1
        sleep 2
    done
    return 1
}
assert_target_service_image() {
    local service=$1
    local ids id image revision
    ids="$("${COMPOSE[@]}" ps --all --quiet "$service")" || return 1
    mapfile -t ids <<<"$ids"
    local count=0
    for id in "${ids[@]}"; do
        [[ -n "$id" ]] || continue
        count=$((count + 1))
        image="$(docker inspect --format '{{.Config.Image}}' "$id")" || return 1
        revision="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$id")" || return 1
        [[ "$image" == "$IMAGE" && "$revision" == "$SHA" ]] || return 1
    done
    ((count == 1))
}
wait_healthy app && assert_target_service_image app \
    || fail 'new app did not pass its readiness health check; project remains stopped.'
compose_call up --no-deps --detach crawler indexer \
    || fail 'new workers failed to start; project remains stopped.'
for service in crawler indexer; do
    wait_healthy "$service" && assert_target_service_image "$service" \
        || fail "new $service worker did not pass its health check; project remains stopped."
done

if [[ -n "$OLD_CURRENT_TARGET" ]]; then
    [[ -L "$ROOT/current" && "$(readlink -- "$ROOT/current")" == "$OLD_CURRENT_TARGET" ]] \
        || fail 'static current changed during deployment; project remains stopped.'
else
    [[ ! -e "$ROOT/current" && ! -L "$ROOT/current" ]] \
        || fail 'static current appeared during fresh deployment; project remains stopped.'
fi
"$SCRIPT_DIR/export-static.sh" --execute --image "$IMAGE" --sha "$SHA" --root "$ROOT" \
    || fail 'static release export failed; project remains stopped.'
STATIC_SWITCHED=1
python3 "$SCRIPT_DIR/release_manifest.py" validate-static --release "$ROOT/releases/$SHA" \
    --expected-sha "$(python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["static_sha"])
PY
)" >/dev/null || fail 'exported static release did not match the target manifest.'
COMPLETE=1
printf 'PASS: project %s migrated once, app and workers are healthy, and static current points to %s.\n' \
    "$PROJECT" "releases/$SHA"
