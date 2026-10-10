#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd -P)"
DEPLOY_DIR="$PROJECT_ROOT/scripts/deploy"
TASK_TMPDIR="${TMPDIR:-/tmp}"
[[ "$TASK_TMPDIR" == /* && -d "$TASK_TMPDIR" ]] || { printf 'test_release_scripts: TMPDIR must exist and be absolute.\n' >&2; exit 1; }
TASK_TMPDIR="$(realpath -e -- "$TASK_TMPDIR")"
[[ "$TASK_TMPDIR" != / && "$TASK_TMPDIR" != "$PROJECT_ROOT" && "$TASK_TMPDIR" != "$PROJECT_ROOT/"* ]] \
    || { printf 'test_release_scripts: unsafe TMPDIR.\n' >&2; exit 1; }
WORK_DIR="$(mktemp -d "$TASK_TMPDIR/newshub-release-tests.XXXXXX")"
DOCKER_LOG="$WORK_DIR/docker.log"
CURL_LOG="$WORK_DIR/curl.log"
trap 'case "$WORK_DIR" in "$TASK_TMPDIR"/newshub-release-tests.*) rm -rf -- "$WORK_DIR";; *) exit 1;; esac' EXIT
mkdir -p "$WORK_DIR/bin" "$WORK_DIR/out"

cat >"$WORK_DIR/bin/docker" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >>"$DOCKER_LOG"
last=''
for argument in "$@"; do last=$argument; done
joined="$*"
case "$1" in
  context)
    case "$2" in
      show) printf 'default\n' ;;
      inspect) printf 'unix:///var/run/docker.sock\n' ;;
    esac
    exit 0
    ;;
  compose)
    case "$joined" in
      *' config --quiet'*)
        previous=''
        compose_file=''
        for argument in "$@"; do
          if [ "$previous" = '--file' ] || [ "$previous" = '-f' ]; then compose_file=$argument; break; fi
          previous=$argument
        done
        [ "$compose_file" = "$MOCK_EXPECTED_COMPOSE" ] || exit 9
        exit 0
        ;;
      *' stop --timeout '*) touch "$MOCK_STOPPED_FILE"; exit 0 ;;
      *' run --rm --no-deps migrate'*) touch "$MOCK_MIGRATE_FILE"; exit 0 ;;
      *' up --no-deps --detach '*) touch "$MOCK_UP_FILE"; exit 0 ;;
      *' ps --all --quiet app') printf 'current-app-id\n'; exit 0 ;;
      *' ps --all --quiet crawler'|*' ps --all --quiet indexer') exit 0 ;;
      *) exit 0 ;;
    esac
    ;;
  image)
    case "$joined" in
      *'org.opencontainers.image.revision'*)
        case "$last" in
          *:????????????????????????????????????????) printf '%s\n' "${last##*:}" ;;
          *) printf '%s\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' ;;
        esac
        exit 0
        ;;
      *'{{.Config.User}}'*) printf '10001:10001\n'; exit 0 ;;
    esac
    ;;
  inspect)
    case "$3" in
      '{{.State.Status}}') printf 'running\n' ;;
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}') printf 'healthy\n' ;;
      '{{.Config.Image}}') printf '%s\n' "${MOCK_CURRENT_IMAGE:-newshub:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;
      *'org.opencontainers.image.revision'*) printf '%s\n' "${MOCK_CURRENT_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;
      *'/var/lib/newshub/db'*) printf '%s\n' "volume|${MOCK_DB_VOLUME:-test_project_db-data}|true" ;;
    esac
    exit 0
    ;;
  ps)
    case "$joined" in
      *'--filter volume='*) printf '%s\n' "${MOCK_RUNNING_CONTAINER:-}"; exit 0 ;;
    esac
    ;;
  run)
    case "$joined" in
      *'sqlite_snapshot.py inspect --source'*)
        printf '%s\n' '{"quick_check":"ok","migrations":[{"app":"api","name":"0002_new"}]}'
        exit 0
        ;;
    esac
    ;;
  create)
    case "$joined" in
      *'target=/source,readonly'*'time.sleep(300)'*)
        [ "${MOCK_FAIL_BACKUP:-0}" = 1 ] && exit 1
        printf 'mock-backup-container\n'
        exit 0
        ;;
      *'target=/source'*'time.sleep(300)'*)
        printf 'mock-restore-container\n'
        exit 0
        ;;
      *) printf 'mock-export-id\n'; exit 0 ;;
    esac
    ;;
  cp)
    case "$2" in
      mock-backup-container:/tmp/snapshot.sqlite3)
        cp -- "$MOCK_VOLUME_SNAPSHOT" "$3" ;;
      mock-backup-container:/tmp/snapshot.sqlite3.manifest.json)
        cp -- "$MOCK_VOLUME_SNAPSHOT.manifest.json" "$3" ;;
      *) [ -f "$2" ] || exit 8 ;;
    esac
    exit 0
    ;;
  exec)
    case "$joined" in
      *'exec --user 0:0 mock-backup-container python -c '*|*'exec --user 0:0 mock-restore-container python -c '*)
        case "$joined" in *'os.chown(path,10001,10001)'*'os.chmod(path,0o600)'*) exit 0 ;; esac
        exit 7
        ;;
      *'exec --user 10001:10001 mock-backup-container python /tmp/sqlite_snapshot.py backup'*)
        touch "$MOCK_BACKUP_RAN_FILE"
        exit 0
        ;;
      *'exec --user 10001:10001 mock-restore-container python /tmp/sqlite_snapshot.py restore'*)
        touch "$MOCK_RESTORE_RAN_FILE"
        exit 0
        ;;
    esac
    exit 0
    ;;
  start|rm) exit 0 ;;
esac
exit 0
SH
cat >"$WORK_DIR/bin/curl" <<'SH'
#!/bin/sh
last=''
for argument in "$@"; do last=$argument; done
printf '%s\n' "$last" >>"$CURL_LOG"
case "$last" in
  */api/health/ready/) exit 0 ;;
  */api/capabilities/) printf '%s\n' '{"site_mode":"read_only","features":{"news":{"enabled":true},"keyword_search":{"enabled":true}}}' ;;
  *) exit 22 ;;
esac
SH
chmod 700 "$WORK_DIR/bin/docker" "$WORK_DIR/bin/curl"
export DOCKER_LOG CURL_LOG
export PATH="$WORK_DIR/bin:$PATH"

python3 - "$WORK_DIR" "$PROJECT_ROOT" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
from scripts.deploy.release_manifest import sha256_exported_release
from scripts.deploy.sqlite_snapshot import backup_database

release_sha = 'a' * 40
target_sha = 'b' * 40
manifest = {
    'schema_version': 1,
    'release_sha': release_sha,
    'image': f'newshub:{release_sha}',
    'migrations': [{'app': 'api', 'name': '0001_initial'}],
    'static_sha': '0' * 64,
}
target_manifest = {
    **manifest,
    'release_sha': target_sha,
    'image': f'newshub:{target_sha}',
    'static_sha': '1' * 64,
}
static_root = root / 'static'
assets_root = static_root / 'assets'
assets_root.mkdir(parents=True)
def make_release(sha, marker):
    release = static_root / 'releases' / sha
    release.mkdir(parents=True)
    (release / 'index.html').write_text(f'<html>{marker}</html>', encoding='utf-8')
    release_assets = release / 'assets'
    release_assets.mkdir()
    shared_asset = assets_root / f'{marker}.js'
    shared_asset.write_text(marker, encoding='utf-8')
    (release_assets / shared_asset.name).hardlink_to(shared_asset)
    return release
old_release = make_release(release_sha, 'old')
new_release = make_release(target_sha, 'new')
manifest['static_sha'] = sha256_exported_release(old_release)
target_manifest['static_sha'] = sha256_exported_release(new_release)
(root / 'release.json').write_text(json.dumps(manifest), encoding='utf-8')
(root / 'target-release.json').write_text(json.dumps(target_manifest), encoding='utf-8')
(root / 'current-new.json').write_text(json.dumps(target_manifest), encoding='utf-8')
(static_root / 'current').symlink_to(f'releases/{release_sha}')
(static_root / 'previous').symlink_to(f'releases/{target_sha}')
(root / 'deploy.env').write_text(
    'DJANGO_SECRET_KEY=synthetic-test-only\nWAITRESS_TRUSTED_PROXY=127.0.0.1\n', encoding='utf-8'
)
target_dist = root / 'target-dist'
(target_dist / 'assets').mkdir(parents=True)
(target_dist / 'index.html').write_text('<html>new</html>', encoding='utf-8')
(target_dist / 'assets' / 'new.js').write_text('new', encoding='utf-8')
connection = sqlite3.connect(root / 'source.sqlite3')
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT, applied TEXT)')
connection.execute("INSERT INTO django_migrations (app,name,applied) VALUES ('api','0001_initial','now')")
connection.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, body TEXT)')
connection.execute("INSERT INTO records (body) VALUES ('committed row')")
connection.commit()
connection.close()
backup_database(root / 'source.sqlite3', root / 'volume-snapshot.sqlite3', root / 'release.json')
PY

export MOCK_VOLUME_SNAPSHOT="$WORK_DIR/volume-snapshot.sqlite3"
export MOCK_BACKUP_RAN_FILE="$WORK_DIR/backup-helper-ran"
export MOCK_RESTORE_RAN_FILE="$WORK_DIR/restore-helper-ran"
chmod 600 "$WORK_DIR/release.json"
"$DEPLOY_DIR/backup.sh" --execute --volume newshub-test_db-data \
    --image "newshub:$(printf 'a%.0s' {1..40})" --sha "$(printf 'a%.0s' {1..40})" \
    --filename volume-copy.sqlite3 --output-dir "$WORK_DIR/out" \
    --manifest "$WORK_DIR/release.json" >/dev/null
[[ -f "$MOCK_BACKUP_RAN_FILE" ]] || { printf 'test_release_scripts: non-root backup helper did not run.\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$WORK_DIR/release.json")" == 600 ]] \
    || { printf 'test_release_scripts: backup staging changed the host manifest mode.\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$WORK_DIR/out/volume-copy.sqlite3")" == 600 ]] \
    || { printf 'test_release_scripts: volume backup host output is not mode 0600.\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$WORK_DIR/out/volume-copy.sqlite3.manifest.json")" == 600 ]] \
    || { printf 'test_release_scripts: volume backup host manifest is not mode 0600.\n' >&2; exit 1; }
rg -q '^create --pull=never --network none --user 10001:10001 --entrypoint python .*time.sleep\(300\)' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: backup helper create argv is incorrect.\n' >&2; exit 1; }
rg -q '^exec --user 0:0 mock-backup-container python -c .*os.chown\(path,10001,10001\).*os.chmod\(path,0o600\)' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: backup manifest was not privately staged for UID 10001.\n' >&2; exit 1; }
rg -q '^exec --user 10001:10001 mock-backup-container python /tmp/sqlite_snapshot.py backup --source /source/db.sqlite3 --output /tmp/snapshot.sqlite3 --release-manifest /tmp/release-manifest.json$' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: backup helper did not run exact argv as UID 10001.\n' >&2; exit 1; }
if rg -q 'python python /tmp/sqlite_snapshot.py' "$DOCKER_LOG"; then
    printf 'test_release_scripts: backup helper argv repeats the interpreter.\n' >&2
    exit 1
fi
: >"$DOCKER_LOG"

PATH="$WORK_DIR/bin:$PATH" "$DEPLOY_DIR/smoke.sh" >/dev/null
PATH="$WORK_DIR/bin:$PATH" "$DEPLOY_DIR/smoke.sh" --local-domain >/dev/null
PATH="$WORK_DIR/bin:$PATH" "$DEPLOY_DIR/smoke.sh" --execute --base-url https://news.example \
    --expected-mode read_only >/dev/null
[[ "$(wc -l <"$CURL_LOG")" -eq 2 ]] || { printf 'test_release_scripts: smoke did not make exactly two read-only requests.\n' >&2; exit 1; }
if PATH="$WORK_DIR/bin:$PATH" "$DEPLOY_DIR/smoke.sh" --execute --base-url https://user@news.example \
    --expected-mode read_only >/dev/null 2>&1; then
    printf 'test_release_scripts: smoke accepted URL credentials.\n' >&2
    exit 1
fi
[[ "$(wc -l <"$CURL_LOG")" -eq 2 ]] || { printf 'test_release_scripts: invalid URL reached curl.\n' >&2; exit 1; }

PATH="$WORK_DIR/bin:$PATH" "$DEPLOY_DIR/backup.sh" --volume newshub-test_db-data \
    --image "newshub:$(printf 'a%.0s' {1..40})" --sha "$(printf 'a%.0s' {1..40})" \
    --filename dry-run.sqlite3 --output-dir "$WORK_DIR/out" --manifest "$WORK_DIR/release.json" >/dev/null
[[ ! -s "$DOCKER_LOG" ]] || { printf 'test_release_scripts: dry-run invoked Docker.\n' >&2; exit 1; }

"$DEPLOY_DIR/backup.sh" --execute --db "$WORK_DIR/source.sqlite3" \
    --output "$WORK_DIR/out/snapshot.sqlite3" --manifest "$WORK_DIR/release.json" >/dev/null
[[ "$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3")" == 600 ]] \
    || { printf 'test_release_scripts: backup was not created mode 0600.\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3.manifest.json")" == 600 ]] \
    || { printf 'test_release_scripts: backup manifest was not created mode 0600.\n' >&2; exit 1; }

"$DEPLOY_DIR/restore.sh" --execute --snapshot "$WORK_DIR/out/snapshot.sqlite3" \
    --target "$WORK_DIR/out/restored.sqlite3" --manifest "$WORK_DIR/release.json" >/dev/null
python3 - "$WORK_DIR/out/restored.sqlite3" <<'PY'
import sqlite3
import sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1])) as connection:
    rows = connection.execute('SELECT body FROM records').fetchall()
    assert rows == [('committed row',)]
    assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)
PY

python3 - "$WORK_DIR/out/existing.sqlite3" "$WORK_DIR/source.sqlite3" <<'PY'
import shutil
import sys
shutil.copyfile(sys.argv[2], sys.argv[1])
PY
OLD_DB_HASH="$(sha256sum "$WORK_DIR/out/existing.sqlite3" | cut -d' ' -f1)"
if "$DEPLOY_DIR/restore.sh" --execute --snapshot "$WORK_DIR/out/snapshot.sqlite3" \
    --target "$WORK_DIR/out/existing.sqlite3" --manifest "$WORK_DIR/release.json" >/dev/null 2>&1; then
    printf 'test_release_scripts: restore replaced an existing DB without stop/backup flags.\n' >&2
    exit 1
fi
[[ "$(sha256sum "$WORK_DIR/out/existing.sqlite3" | cut -d' ' -f1)" == "$OLD_DB_HASH" ]] \
    || { printf 'test_release_scripts: rejected restore changed the existing DB.\n' >&2; exit 1; }

"$DEPLOY_DIR/backup.sh" --execute --db "$WORK_DIR/out/existing.sqlite3" \
    --output "$WORK_DIR/out/prior.sqlite3" --manifest "$WORK_DIR/release.json" >/dev/null
"$DEPLOY_DIR/restore.sh" --execute --snapshot "$WORK_DIR/out/snapshot.sqlite3" \
    --target "$WORK_DIR/out/existing.sqlite3" --manifest "$WORK_DIR/release.json" \
    --replace --writers-stopped --prior-backup "$WORK_DIR/out/prior.sqlite3" >/dev/null

MODE_SNAPSHOT="$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3")"
MODE_SNAPSHOT_MANIFEST="$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3.manifest.json")"
MODE_PRIOR="$(stat -c '%a' "$WORK_DIR/out/prior.sqlite3")"
MODE_PRIOR_MANIFEST="$(stat -c '%a' "$WORK_DIR/out/prior.sqlite3.manifest.json")"
MODE_RELEASE_MANIFEST="$(stat -c '%a' "$WORK_DIR/release.json")"
"$DEPLOY_DIR/restore.sh" --execute --snapshot "$WORK_DIR/out/snapshot.sqlite3" \
    --volume newshub-test_db-data --image "newshub:$(printf 'a%.0s' {1..40})" \
    --sha "$(printf 'a%.0s' {1..40})" --manifest "$WORK_DIR/release.json" \
    --replace --writers-stopped --prior-backup "$WORK_DIR/out/prior.sqlite3" >/dev/null
[[ -f "$MOCK_RESTORE_RAN_FILE" ]] || { printf 'test_release_scripts: non-root restore helper did not run.\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3")" == "$MODE_SNAPSHOT" \
    && "$(stat -c '%a' "$WORK_DIR/out/snapshot.sqlite3.manifest.json")" == "$MODE_SNAPSHOT_MANIFEST" \
    && "$(stat -c '%a' "$WORK_DIR/out/prior.sqlite3")" == "$MODE_PRIOR" \
    && "$(stat -c '%a' "$WORK_DIR/out/prior.sqlite3.manifest.json")" == "$MODE_PRIOR_MANIFEST" \
    && "$(stat -c '%a' "$WORK_DIR/release.json")" == "$MODE_RELEASE_MANIFEST" ]] \
    || { printf 'test_release_scripts: restore staging changed host artifact permissions.\n' >&2; exit 1; }
rg -q '^exec --user 0:0 mock-restore-container python -c .*os.chown\(path,10001,10001\).*os.chmod\(path,0o600\)' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: restore artifacts were not privately staged for UID 10001.\n' >&2; exit 1; }
rg -q '^create --pull=never --network none --entrypoint python --user 10001:10001 .*target=/source .*time.sleep\(300\)' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: restore helper is not bounded and pinned to UID 10001.\n' >&2; exit 1; }
rg -q '^exec --user 10001:10001 mock-restore-container python /tmp/sqlite_snapshot.py restore --source /tmp/snapshot.sqlite3 --target /source/db.sqlite3 --release-manifest /tmp/release-manifest.json --replace --writers-stopped --prior-backup /tmp/prior.sqlite3$' "$DOCKER_LOG" \
    || { printf 'test_release_scripts: restore helper did not run exact argv as UID 10001.\n' >&2; exit 1; }

: >"$DOCKER_LOG"
MOCK_RUNNING_CONTAINER=running-container PATH="$WORK_DIR/bin:$PATH" \
    "$DEPLOY_DIR/restore.sh" --execute --snapshot "$WORK_DIR/out/snapshot.sqlite3" \
    --volume newshub-test_db-data --image "newshub:$(printf 'a%.0s' {1..40})" \
    --sha "$(printf 'a%.0s' {1..40})" --manifest "$WORK_DIR/release.json" >/dev/null 2>&1 && {
        printf 'test_release_scripts: volume restore allowed a running writer.\n' >&2
        exit 1
    }
if rg -q 'create|start|cp|up' "$DOCKER_LOG"; then
    printf 'test_release_scripts: volume negative test created or changed Docker resources.\n' >&2
    exit 1
fi

PROJECT=test_project
DB_VOLUME=${PROJECT}_db-data
MOCK_STOPPED_FILE="$WORK_DIR/project-stopped"
MOCK_MIGRATE_FILE="$WORK_DIR/migration-ran"
MOCK_UP_FILE="$WORK_DIR/project-started"
export MOCK_STOPPED_FILE MOCK_MIGRATE_FILE MOCK_UP_FILE MOCK_DB_VOLUME="$DB_VOLUME"
export MOCK_EXPECTED_COMPOSE="$PROJECT_ROOT/compose.prod.yaml"
[[ -f "$MOCK_EXPECTED_COMPOSE" ]] || { printf 'test_release_scripts: production compose file was not found at repository root.\n' >&2; exit 1; }
export MOCK_CURRENT_IMAGE="newshub:$(printf 'a%.0s' {1..40})"
export MOCK_CURRENT_SHA="$(printf 'a%.0s' {1..40})"
export PATH="$WORK_DIR/bin:$PATH"
: >"$DOCKER_LOG"
deploy_args=(--env-file "$WORK_DIR/deploy.env" --project "$PROJECT" \
    --sha "$(printf 'b%.0s' {1..40})" --image "newshub:$(printf 'b%.0s' {1..40})" \
    --root "$WORK_DIR/static" --manifest "$WORK_DIR/target-release.json" \
    --current-manifest "$WORK_DIR/release.json" --db-volume "$DB_VOLUME" \
    --backup-output "$WORK_DIR/out/deploy.sqlite3")
"$DEPLOY_DIR/deploy.sh" "${deploy_args[@]}" >/dev/null
[[ ! -s "$DOCKER_LOG" ]] || { printf 'test_release_scripts: deploy dry-run invoked Docker.\n' >&2; exit 1; }
if "$DEPLOY_DIR/deploy.sh" --env-file "$WORK_DIR/deploy.env" --project "$PROJECT" \
    --sha bad --image bad --root "$WORK_DIR/static" --manifest "$WORK_DIR/target-release.json" \
    --current-manifest "$WORK_DIR/release.json" --db-volume "$DB_VOLUME" \
    --backup-output "$WORK_DIR/out/deploy.sqlite3" >/dev/null 2>&1; then
    printf 'test_release_scripts: deploy accepted an invalid SHA.\n' >&2
    exit 1
fi
if MOCK_FAIL_BACKUP=1 "$DEPLOY_DIR/deploy.sh" --execute "${deploy_args[@]}" >/dev/null 2>&1; then
    printf 'test_release_scripts: deploy continued after a backup failure.\n' >&2
    exit 1
fi
[[ -e "$MOCK_STOPPED_FILE" && ! -e "$MOCK_MIGRATE_FILE" && ! -e "$MOCK_UP_FILE" ]] \
    || { printf 'test_release_scripts: backup failure did not fail closed before migration/start.\n' >&2; exit 1; }
[[ "$(readlink -- "$WORK_DIR/static/current")" == "releases/$(printf 'a%.0s' {1..40})" ]] \
    || { printf 'test_release_scripts: failed deployment changed static current.\n' >&2; exit 1; }
[[ ! -e "$WORK_DIR/out/deploy.sqlite3" ]] \
    || { printf 'test_release_scripts: failed backup left a published artifact.\n' >&2; exit 1; }

rm -f -- "$MOCK_STOPPED_FILE" "$MOCK_MIGRATE_FILE" "$MOCK_UP_FILE"
: >"$DOCKER_LOG"
rm -f -- "$WORK_DIR/static/current"
ln -s -- "releases/$(printf 'b%.0s' {1..40})" "$WORK_DIR/static/current"
rollback_args=(--env-file "$WORK_DIR/deploy.env" --project "$PROJECT" \
    --sha "$(printf 'a%.0s' {1..40})" --image "newshub:$(printf 'a%.0s' {1..40})" \
    --root "$WORK_DIR/static" --manifest "$WORK_DIR/release.json" \
    --current-manifest "$WORK_DIR/current-new.json" --db-volume "$DB_VOLUME")
"$DEPLOY_DIR/rollback.sh" "${rollback_args[@]}" >/dev/null
[[ ! -e "$MOCK_STOPPED_FILE" ]] || { printf 'test_release_scripts: rollback dry-run changed project state.\n' >&2; exit 1; }
: >"$DOCKER_LOG"
export MOCK_CURRENT_IMAGE="newshub:$(printf 'b%.0s' {1..40})"
export MOCK_CURRENT_SHA="$(printf 'b%.0s' {1..40})"
if "$DEPLOY_DIR/rollback.sh" --execute "${rollback_args[@]}" >/dev/null 2>&1; then
    printf 'test_release_scripts: rollback accepted a newer incompatible migration set.\n' >&2
    exit 1
fi
[[ -e "$MOCK_STOPPED_FILE" && ! -e "$MOCK_UP_FILE" ]] \
    || { printf 'test_release_scripts: incompatible rollback did not remain stopped.\n' >&2; exit 1; }
if rg -q ' up --no-deps --detach ' "$DOCKER_LOG"; then
    printf 'test_release_scripts: incompatible rollback started a service.\n' >&2
    exit 1
fi
[[ "$(readlink -- "$WORK_DIR/static/current")" == "releases/$(printf 'b%.0s' {1..40})" ]] \
    || { printf 'test_release_scripts: incompatible rollback changed static current.\n' >&2; exit 1; }

printf 'PASS: release dry-run, fail-closed deploy/rollback, smoke, SQLite backup/restore, and active-volume rejection tests.\n'
