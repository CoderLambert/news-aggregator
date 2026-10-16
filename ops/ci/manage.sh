#!/usr/bin/env bash
set -Eeuo pipefail

# Operates only on this explicit Compose project. Does not touch other Docker
# projects, host services, NewsHub production data or CI budgets.
CI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT="newshub-ci"
REPO="CoderLambert/news-aggregator"
DATA_DIR="${CI_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/newshub-ci}"
TOKEN_FILE="$DATA_DIR/registration-token"
COMMAND="${1:-help}"

die() { printf 'newshub-ci: %s\n' "$*" >&2; exit 2; }
usage() {
    cat <<'HELP'
Usage: bash ops/ci/manage.sh <install|start|stop|status|logs|update|doctor|uninstall>
  install   Build isolated runner + DinD, register via gh short-lived token, start.
  start     Start an already registered runner without requesting a new token.
  stop      Stop runner and its private DinD (does not delete volumes).
  status    Display Compose state and (if permitted) GitHub runner status.
  logs      Follow runner logs; Ctrl+C to stop following.
  update    Rebuild and restart the registered runner; keep volumes.
  doctor    Read-only host/Compose validation and resource checks.
  uninstall Stop/delete only this Compose project's containers and networks.
            Does NOT remove volumes or unregister the GitHub-side runner.
HELP
}
compose() {
    CI_DATA_DIR="$DATA_DIR" docker compose --project-name "$PROJECT" -f "$CI_DIR/compose.yaml" "$@"
}
prepare_paths() {
    [[ "$DATA_DIR" == /* && "$DATA_DIR" != / ]] || die "CI_DATA_DIR must be an absolute, non-root path"
    [[ ! -L "$DATA_DIR" ]] || die "CI_DATA_DIR must not be a symlink"
    mkdir -p -- "$DATA_DIR"
    chmod 700 "$DATA_DIR"
    [[ ! -L "$TOKEN_FILE" ]] || die "registration-token must not be a symlink"
    if [[ ! -e "$TOKEN_FILE" ]]; then
        (umask 077; : > "$TOKEN_FILE")
    fi
    [[ -f "$TOKEN_FILE" ]] || die "registration-token must be a regular file"
    chmod 600 "$TOKEN_FILE"
}
clear_token() {
    if [[ -f "$TOKEN_FILE" && ! -L "$TOKEN_FILE" ]]; then
        : > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
    fi
}
preflight() {
    command -v docker >/dev/null 2>&1 || die "Docker CLI not installed"
    docker info >/dev/null || die "Docker daemon is unavailable"
    docker compose version >/dev/null || die "Docker Compose v2 is unavailable"
    local endpoint
    endpoint="$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    [[ "$endpoint" == unix://* || "${DOCKER_HOST:-}" == unix://* ]] \
        || die "Refusing to mutate a non-Unix/remote Docker daemon"
    prepare_paths
    compose config --quiet || die "Compose configuration invalid"
}
configured() {
    compose run --rm --no-deps --entrypoint /bin/sh runner \
        -c 'test -s /runner/data/.runner' >/dev/null 2>&1
}
wait_for_registration() {
    local i
    for ((i=0; i<90; i++)); do
        if compose exec -T runner /bin/sh -c \
            'test -s /runner/data/.runner && docker info >/dev/null 2>&1' >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}
report_status() {
    compose ps
    if command -v gh >/dev/null 2>&1 && gh auth status --hostname github.com >/dev/null 2>&1; then
        gh api "repos/$REPO/actions/runners" \
            --jq '.runners[] | select(.name=="omarchy-newshub") | {id,name,status,busy,labels:[.labels[].name]}' \
            || printf 'GitHub runner status API unavailable; check repository Actions settings.\n'
    fi
}

case "$COMMAND" in
    help|-h|--help) usage ;;
    doctor)
        preflight
        printf 'Local Unix Docker daemon and CI Compose configuration: PASS\n'
        docker info --format 'CPUs={{.NCPU}} MemoryBytes={{.MemTotal}}'
        printf 'State directory: %s\n' "$DATA_DIR"
        printf 'No GitHub runner registration or service start was performed.\n'
        ;;
    install)
        preflight
        compose build runner
        trap clear_token EXIT
        if configured; then
            printf 'Existing runner configuration found; reusing it.\n'
        else
            command -v gh >/dev/null 2>&1 || die "Install gh and authenticate: gh auth login"
            gh auth status --hostname github.com >/dev/null 2>&1 || die "Authenticate gh to github.com first"
            # A one-time registration token is NOT a PAT and must never be
            # stored in .env, source control or the persistent container config.
            token="$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq '.token')" \
                || die "GitHub registration denied. Verify repository Administration permission."
            [[ "$token" != "" && "$token" != "null" ]] || die "GitHub returned an empty runner token"
            printf '%s' "$token" > "$TOKEN_FILE"
            unset token
        fi
        compose up -d --no-build
        if ! wait_for_registration; then
            compose logs --tail=60 runner
            die "Registration/daemon health not reached in 180s"
        fi
        clear_token
        report_status
        ;;
    start)
        preflight
        configured || die "Runner has not been registered; use install"
        compose up -d --no-build
        report_status
        ;;
    stop)
        preflight
        compose stop runner docker
        ;;
    status)
        preflight
        report_status
        ;;
    logs)
        preflight
        compose logs --tail=100 --follow runner
        ;;
    update)
        preflight
        configured || die "Runner not registered; use install"
        compose up -d --build
        wait_for_registration || die "Runner not ready after update"
        report_status
        ;;
    uninstall)
        preflight
        compose down --remove-orphans
        printf 'Project stopped; volumes and GitHub runner registration remain intact.\n'
        ;;
    *) usage; die "Unknown operation: $COMMAND" ;;
esac
