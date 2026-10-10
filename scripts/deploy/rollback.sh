#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
COMPOSE_FILE="$PROJECT_ROOT/compose.prod.yaml"
EXECUTE=0
ENV_FILE=""
PROJECT=""
SHA=""
IMAGE=""
ROOT=""
MANIFEST=""
CURRENT_MANIFEST=""
DB_VOLUME=""
WINDOW_STARTED=0
COMPLETE=0
STATIC_SWITCHED=0
OLD_CURRENT_TARGET=""

usage() {
    cat <<'EOF'
Usage: rollback.sh [--execute] --env-file ABSOLUTE-FILE --project NAME \
    --sha 40-HEX-SHA --image IMAGE --root ABSOLUTE-STATIC-ROOT \
    --manifest TARGET-OLD-MANIFEST --current-manifest CURRENT-MANIFEST \
    --db-volume PROJECT_db-data

Without --execute this validates local release/static inputs and prints a plan.
Execution stops only the selected project's app/workers, requires an exact database
migration-set match for the target manifest, starts and health-checks that release,
then atomically points static current at the existing target release.
EOF
}

fail() {
    printf 'rollback: %s\n' "$1" >&2
    exit 2
}

restore_current_if_needed() {
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
            printf 'rollback: failed to confirm fail-closed stop for this Compose project.\n' >&2
        fi
        if ! restore_current_if_needed; then
            printf 'rollback: failed to restore the prior static current link.\n' >&2
            status=1
        fi
        printf 'rollback: this project remains stopped after failure.\n' >&2
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --env-file) (($# >= 2)) || fail '--env-file requires a value.'; ENV_FILE=$2; shift 2 ;;
        --project) (($# >= 2)) || fail '--project requires a value.'; PROJECT=$2; shift 2 ;;
        --sha) (($# >= 2)) || fail '--sha requires a value.'; SHA=$2; shift 2 ;;
        --image) (($# >= 2)) || fail '--image requires a value.'; IMAGE=$2; shift 2 ;;
        --root) (($# >= 2)) || fail '--root requires a value.'; ROOT=$2; shift 2 ;;
        --manifest) (($# >= 2)) || fail '--manifest requires a value.'; MANIFEST=$2; shift 2 ;;
        --current-manifest) (($# >= 2)) || fail '--current-manifest requires a value.'; CURRENT_MANIFEST=$2; shift 2 ;;
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
[[ -f "$CURRENT_MANIFEST" && ! -L "$CURRENT_MANIFEST" ]] \
    || fail '--current-manifest must be a regular current release manifest.'
python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$MANIFEST" >/dev/null \
    || fail 'target release manifest is invalid.'
python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$CURRENT_MANIFEST" >/dev/null \
    || fail 'current release manifest is invalid.'
TARGET_SHA="$(python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["release_sha"])
PY
)"
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
TARGET_STATIC_SHA="$(python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["static_sha"])
PY
)"
CURRENT_STATIC_SHA="$(python3 - "$CURRENT_MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["static_sha"])
PY
)"
[[ "$TARGET_SHA" == "$SHA" ]] || fail 'target manifest SHA does not match --sha.'

COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
compose_call() {
    NEWSHUB_IMAGE="$IMAGE" NEWSHUB_ENV_FILE="$ENV_FILE" "${COMPOSE[@]}" "$@"
}

if [[ ! -d "$ROOT" || -L "$ROOT" || ! -L "$ROOT/current" ]]; then
    fail '--root and current must be real release storage with a current symlink.'
fi
OLD_CURRENT_TARGET="$(readlink -- "$ROOT/current")" || fail 'could not read current static release.'
[[ "$OLD_CURRENT_TARGET" == "releases/$CURRENT_SHA" || "$OLD_CURRENT_TARGET" == "releases/$SHA" ]] \
    || fail 'current static must match either --current-manifest or the requested rollback target.'
python3 "$SCRIPT_DIR/release_manifest.py" validate-static --release "$ROOT/releases/$SHA" \
    --expected-sha "$TARGET_STATIC_SHA" >/dev/null \
    || fail 'target static release is missing or does not match its manifest.'
if [[ "$OLD_CURRENT_TARGET" == "releases/$CURRENT_SHA" ]]; then
    python3 "$SCRIPT_DIR/release_manifest.py" validate-static --release "$ROOT/$OLD_CURRENT_TARGET" \
        --expected-sha "$CURRENT_STATIC_SHA" >/dev/null \
        || fail 'current static release does not match --current-manifest.'
fi
[[ -e "$ROOT/previous" || -L "$ROOT/previous" ]] && [[ ! -L "$ROOT/previous" ]] \
    && fail 'previous static path exists but is not a symlink.'

if ((!EXECUTE)); then
    printf 'Dry run only: would stop only project %s, require the database migrations to exactly match target %s, health-check its app/workers, then point current at %s; no Docker or filesystem changes.\n' \
        "$PROJECT" "$SHA" "releases/$SHA"
    exit 0
fi

command -v docker >/dev/null 2>&1 || fail 'Docker CLI is unavailable.'
command -v python3 >/dev/null 2>&1 || fail 'python3 is unavailable.'
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
python3 "$SCRIPT_DIR/release_manifest.py" validate --manifest "$CURRENT_MANIFEST" \
    --image "$CURRENT_IMAGE" --sha "$CURRENT_SHA" >/dev/null \
    || fail 'current image revision/user did not match the current manifest.'
compose_call config --quiet || fail 'production Compose configuration is incomplete or invalid.'

app_ids_raw="$("${COMPOSE[@]}" ps --all --quiet app)" || fail 'could not inspect the current app container.'
mapfile -t app_ids <<<"$app_ids_raw"
filtered_ids=()
for item in "${app_ids[@]}"; do [[ -n "$item" ]] && filtered_ids+=("$item"); done
((${#filtered_ids[@]} <= 1)) || fail 'rollback requires at most one app container in the selected project.'
if ((${#filtered_ids[@]} == 1)); then
    APP_ID="${filtered_ids[0]}"
    app_image="$(docker inspect --format '{{.Config.Image}}' "$APP_ID")" || fail 'could not inspect current app image.'
    app_revision="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$APP_ID")" \
        || fail 'could not inspect current app revision.'
    app_db_mount="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/newshub/db"}}{{.Type}}|{{.Name}}|{{.RW}}{{end}}{{end}}' "$APP_ID")" \
        || fail 'could not inspect current app database mount.'
    [[ "$app_image" == "$CURRENT_IMAGE" && "$app_revision" == "$CURRENT_SHA" ]] \
        || fail 'existing app container does not match --current-manifest.'
    [[ "$app_db_mount" == "volume|$DB_VOLUME|true" ]] \
        || fail 'existing app does not mount the explicitly requested database volume read/write.'
fi

WINDOW_STARTED=1
compose_call stop --timeout 45 crawler indexer app \
    || fail 'could not stop all project writers; project remains stopped.'
running="$(docker ps --quiet --filter "volume=$DB_VOLUME")" \
    || fail 'could not verify that database volume writers stopped.'
[[ -z "$running" ]] || fail 'database volume still has a running container; project remains stopped.'
schema_result="$(docker run --rm --pull=never --network none --entrypoint python \
    --mount "type=volume,source=$DB_VOLUME,target=/source,readonly" \
    --mount "type=bind,source=$SCRIPT_DIR/sqlite_snapshot.py,target=/tmp/sqlite_snapshot.py,readonly" \
    "$IMAGE" /tmp/sqlite_snapshot.py inspect --source /source/db.sqlite3)" \
    || fail 'could not read a valid SQLite schema from the stopped database volume.'
python3 - "$MANIFEST" "$schema_result" <<'PY' \
    || fail 'database migrations do not exactly match the rollback target manifest.'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    expected = json.load(stream)["migrations"]
try:
    actual = json.loads(sys.argv[2])["migrations"]
except (json.JSONDecodeError, KeyError, TypeError):
    raise SystemExit(1)
raise SystemExit(0 if actual == expected else 1)
PY

compose_call up --no-deps --detach app || fail 'target app failed to start; project remains stopped.'
wait_healthy() {
    local service=$1
    local deadline=$((SECONDS + 300))
    local ids status health found id
    while ((SECONDS < deadline)); do
        ids="$("${COMPOSE[@]}" ps --all --quiet "$service")" || return 1
        mapfile -t ids <<<"$ids"
        found=0
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
    local ids id image revision count=0
    ids="$("${COMPOSE[@]}" ps --all --quiet "$service")" || return 1
    mapfile -t ids <<<"$ids"
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
    || fail 'target app did not pass its readiness health check; project remains stopped.'
compose_call up --no-deps --detach crawler indexer \
    || fail 'target workers failed to start; project remains stopped.'
for service in crawler indexer; do
    wait_healthy "$service" && assert_target_service_image "$service" \
        || fail "target $service worker did not pass its health check; project remains stopped."
done

[[ -L "$ROOT/current" && "$(readlink -- "$ROOT/current")" == "$OLD_CURRENT_TARGET" ]] \
    || fail 'static current changed during rollback; project remains stopped.'
if [[ "$OLD_CURRENT_TARGET" != "releases/$SHA" ]]; then
    previous_temporary="$ROOT/.previous.new.$$"
    current_temporary="$ROOT/.current.new.$$"
    [[ ! -e "$previous_temporary" && ! -L "$previous_temporary" \
        && ! -e "$current_temporary" && ! -L "$current_temporary" ]] \
        || fail 'temporary static link path already exists.'
    ln -s -- "$OLD_CURRENT_TARGET" "$previous_temporary" || fail 'could not stage previous static link.'
    mv -Tf -- "$previous_temporary" "$ROOT/previous" || fail 'could not preserve the previous static link.'
    ln -s -- "releases/$SHA" "$current_temporary" || fail 'could not stage rollback static link.'
    mv -Tf -- "$current_temporary" "$ROOT/current" || fail 'could not switch current to the validated target release.'
    STATIC_SWITCHED=1
fi
COMPLETE=1
printf 'PASS: project %s runs validated release %s against an exactly matching database schema.\n' \
    "$PROJECT" "$SHA"
