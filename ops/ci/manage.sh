#!/usr/bin/env bash
set -Eeuo pipefail

# Operates only on this explicit Compose project. Does not touch other Docker
# projects, host services, NewsHub production data or CI budgets.
CI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT="newshub-ci"
REPO="CoderLambert/news-aggregator"
DATA_DIR="${CI_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/newshub-ci}"
BACKEND_TOKEN_FILE="$DATA_DIR/registration-token"
FRONTEND_TOKEN_FILE="$DATA_DIR/registration-token-frontend"
COMMAND="${1:-help}"

die() { printf 'newshub-ci: %s\n' "$*" >&2; exit 2; }
usage() {
    cat <<'HELP'
Usage: bash ops/ci/manage.sh <install|start|stop|status|logs|update|doctor|uninstall>
  install   Build one runner image + DinD, register two independent runners.
  start     Start both registered runners without requesting new tokens.
  stop      Stop runner and its private DinD (does not delete volumes).
  status    Display Compose and both GitHub runner statuses.
  logs      Follow both runners and the isolated Docker daemon.
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
    local file
    for file in "$BACKEND_TOKEN_FILE" "$FRONTEND_TOKEN_FILE"; do
        [[ ! -L "$file" ]] || die "registration token must not be a symlink"
        if [[ ! -e "$file" ]]; then
            (umask 077; : > "$file")
        fi
        [[ -f "$file" ]] || die "registration token must be a regular file"
        chmod 600 "$file"
    done
}
clear_tokens() {
    local file
    for file in "$BACKEND_TOKEN_FILE" "$FRONTEND_TOKEN_FILE"; do
        if [[ -f "$file" && ! -L "$file" ]]; then
            : > "$file"
            chmod 600 "$file"
        fi
    done
}
preflight() {
    command -v docker >/dev/null 2>&1 || die "Docker CLI not installed"
    docker info >/dev/null || die "Docker daemon is unavailable"
    docker compose version >/dev/null || die "Docker Compose v2 is unavailable"
    local endpoint
    endpoint="$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    [[ "$endpoint" == unix://* || "${DOCKER_HOST:-}" == unix://* ]] \
        || die "Refusing to mutate a non-Unix/remote Docker daemon"
    if [[ "$COMMAND" != doctor ]]; then
        prepare_paths
    fi
    compose config --quiet || die "Compose configuration invalid"
}
configured() {
    local service="$1"
    compose run --rm --no-deps --entrypoint /bin/sh "$service" \
        -c 'test -s /runner/data/.runner' >/dev/null 2>&1
}
wait_for_registration() {
    local service="$1" check='test -s /runner/data/.runner' i
    if [[ "$service" == runner ]]; then
        check="$check && docker info >/dev/null 2>&1"
    fi
    for ((i=0; i<90; i++)); do
        if compose exec -T "$service" /bin/sh -c "$check" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}
issue_registration_token() {
    local destination="$1" token
    command -v gh >/dev/null 2>&1 || die "Install gh and authenticate: gh auth login"
    gh auth status --hostname github.com >/dev/null 2>&1 || die "Authenticate gh to github.com first"
    token="$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq '.token')" \
        || die "GitHub registration denied. Verify repository Administration permission."
    [[ -n "$token" && "$token" != null ]] || die "GitHub returned an empty runner token"
    printf '%s' "$token" > "$destination"
    unset token
}
report_status() {
    compose ps
    if command -v gh >/dev/null 2>&1 && gh auth status --hostname github.com >/dev/null 2>&1; then
        gh api "repos/$REPO/actions/runners?per_page=100" \
            --jq '.runners[] | select(.name=="omarchy-newshub" or .name=="omarchy-newshub-frontend") | {id,name,status,busy,labels:[.labels[].name]}' \
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
        # Build once: runner-frontend reuses the exact same local image.
        compose build runner
        trap clear_tokens EXIT
        if configured runner; then
            printf 'Backend runner identity found; reusing it.\n'
        else
            issue_registration_token "$BACKEND_TOKEN_FILE"
        fi
        if configured runner-frontend; then
            printf 'Frontend runner identity found; reusing it.\n'
        else
            issue_registration_token "$FRONTEND_TOKEN_FILE"
        fi
        compose up -d --no-build
        if ! wait_for_registration runner || ! wait_for_registration runner-frontend; then
            compose logs --tail=60 runner runner-frontend docker
            die "One of two runners did not become ready within the registration window"
        fi
        clear_tokens
        report_status
        ;;
    start)
        preflight
        configured runner && configured runner-frontend || die "Both runners must be registered; run install"
        compose up -d --no-build
        report_status
        ;;
    stop)
        preflight
        compose stop runner runner-frontend docker
        ;;
    status)
        preflight
        report_status
        ;;
    logs)
        preflight
        compose logs --tail=100 --follow runner runner-frontend docker
        ;;
    update)
        preflight
        configured runner && configured runner-frontend || die "Both runners must be registered; run install"
        compose up -d --build
        wait_for_registration runner && wait_for_registration runner-frontend || die "One of two runners not ready after update"
        report_status
        ;;
    uninstall)
        preflight
        compose down --remove-orphans
        printf 'Project stopped; volumes and GitHub runner registration remain intact.\n'
        ;;
    *) usage; die "Unknown operation: $COMMAND" ;;
esac
