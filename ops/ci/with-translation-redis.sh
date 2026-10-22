#!/usr/bin/env bash
# Authenticated, network-free Redis shared through the job's disposable TMPDIR.
# A Unix socket works across the private DinD shared-workspace boundary.
set -euo pipefail
[[ "$#" -gt 0 ]] || { echo 'usage: with-translation-redis.sh COMMAND [ARG...]' >&2; exit 2; }
: "${TMPDIR:?Set the isolated shared CI temporary directory}"
redis_dir="$(mktemp -d "$TMPDIR/newshub-translation-redis.XXXXXX")"
redis_container=''
cleanup() {
    if [[ -n "$redis_container" ]]; then docker rm -f "$redis_container" >/dev/null 2>&1 || true; fi
    rm -rf -- "$redis_dir"
}
trap cleanup EXIT
python_bin="${PYTHON_BIN:-backend/venv/bin/python}"
redis_image="$("$python_bin" -c 'import yaml; print(yaml.safe_load(open("compose.translation.yaml"))["services"]["translation-redis"]["image"])')"
redis_container="$(docker run -d --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --label newshub.synthetic=translation-ci \
    --mount "type=bind,source=$redis_dir,target=/socket" \
    --entrypoint redis-server "$redis_image" \
    --port 0 --unixsocket /socket/redis.sock --unixsocketperm 700 \
    --save '' --appendonly no --maxmemory 64mb --maxmemory-policy noeviction \
    --requirepass synthetic-translation-only)"
ready=0
for _ in {1..40}; do
    if [[ "$(docker exec "$redis_container" redis-cli -s /socket/redis.sock \
        --no-auth-warning -a synthetic-translation-only ping 2>/dev/null || true)" == PONG ]]; then
        ready=1; break
    fi
    sleep 0.25
done
[[ "$ready" == 1 ]] || { echo 'isolated translation Redis did not become ready' >&2; exit 1; }
export TEST_TRANSLATION_REDIS_SOCKET="$redis_dir/redis.sock"
unset TEST_TRANSLATION_REDIS_URL
"$@"
