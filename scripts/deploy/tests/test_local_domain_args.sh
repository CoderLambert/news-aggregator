#!/usr/bin/env bash
set -Eeuo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$TEST_DIR/../../.." && pwd -P)"
SMOKE_SCRIPT="$PROJECT_ROOT/scripts/deploy/local-domain-smoke.sh"
task_test_root="$(mktemp -d "${TMPDIR:-/tmp}/newshub-local-domain-args.XXXXXX")"
trap 'rm -rf -- "$task_test_root"' EXIT

task_bin="$task_test_root/bin"
task_temp="$task_test_root/tmp"
task_log="$task_test_root/docker.log"
CERTUTIL_LOG="$task_test_root/certutil.log"
mkdir -p -- "$task_bin" "$task_temp"

fail() {
    printf 'test_local_domain_args: %s\n' "$1" >&2
    exit 1
}

expect_exit() {
    local expected=$1
    shift
    local actual=0
    "$@" >/dev/null 2>&1 || actual=$?
    [[ "$actual" == "$expected" ]] || fail "expected exit $expected, got $actual: $*"
}

assert_no_docker_calls() {
    [[ ! -s "$task_log" ]] || fail 'a preflight case unexpectedly called Docker.'
}

cat >"$task_bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >>"$DOCKER_LOG"
if [[ "$1" == compose && "$2" == version ]]; then
    exit 0
fi
if [[ "$1" == image && "$2" == inspect ]]; then
    image="${@: -1}"
    if [[ "$image" == "$NGINX_IMAGE" && "${MOCK_NGINX_MISSING:-0}" == 1 ]]; then
        exit 1
    fi
    if [[ "$image" == "$APP_IMAGE" && "${MOCK_APP_MISSING:-0}" == 1 ]]; then
        exit 1
    fi
    if [[ "$*" == *org.opencontainers.image.revision* ]]; then
        printf '%s\n' "$MOCK_IMAGE_SHA"
    elif [[ "$*" == *'json .RepoDigests'* ]]; then
        printf '["nginx@sha256:mock"]\n'
    else
        printf 'sha256:local-mock-image\n'
    fi
    exit 0
fi
if [[ "$1" == create ]]; then
    printf 'fake-export-container\n'
    exit 0
fi
if [[ "$1" == cp ]]; then
    target="${@: -1}"
    mkdir -p -- "$target/assets"
    printf '<html><div id="root"></div></html>\n' >"$target/index.html"
    printf 'mock-asset\n' >"$target/assets/app-abc12345.js"
    exit 0
fi
if [[ "$1" == compose ]]; then
    if [[ "$*" == *' config --quiet' ]]; then
        compose_file=""
        for ((index = 1; index <= $#; index++)); do
            if [[ "${!index}" == --file ]]; then
                next=$((index + 1))
                compose_file="${!next}"
                break
            fi
        done
        [[ -n "$compose_file" ]] || exit 1
        rg -q 'WAITRESS_PORT: "9527"' "$compose_file" || exit 1
        rg -q 'network_mode: service:gateway' "$compose_file" || exit 1
        rg -q 'internal: true' "$compose_file" || exit 1
        ! rg -q '^    ports:' "$compose_file" || exit 1
    fi
    if [[ "$*" == *' ps -q gateway' ]]; then
        printf 'fake-gateway-container\n'
    elif [[ "$*" == *'manage.py shell -c'* ]]; then
        printf '1\n'
    fi
    exit 0
fi
if [[ "$1" == inspect ]]; then
    printf '172.28.0.2\n'
    exit 0
fi
if [[ "$1" == run && " $* " == *" -d "* ]]; then
    printf 'fake-sse-container\n'
    exit 0
fi
if [[ "$1" == run && "$*" == *'nginx -v'* ]]; then
    printf 'nginx version: nginx/1.30.5\n'
    exit 0
fi
exit 0
MOCK

cat >"$task_bin/openssl" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >>"$OPENSSL_LOG"
if [[ "$1" == rand ]]; then
    printf '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n'
    exit 0
fi
while (($#)); do
    case "$1" in
        -keyout|-out)
            [[ $# -ge 2 ]] || exit 1
            mkdir -p -- "$(dirname -- "$2")"
            : >"$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done
MOCK

cat >"$task_bin/certutil" <<MOCK
#!/usr/bin/env bash
printf '%s HOME=%s API_KEY_PRESENT=%s\n' "\$*" "\$HOME" "\${DASHSCOPE_CODING_API_KEY:+yes}" >>"$CERTUTIL_LOG"
exit 0
MOCK

cat >"$task_bin/curl" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
exit 0
MOCK

cat >"$task_bin/python-task" <<'MOCK'
#!/usr/bin/env bash
set -eu
if [[ "${1:-}" == -c ]]; then
    if [[ "$2" == *'cleanup_status'* ]]; then
        exec "$REAL_PYTHON" -c "$2" "${@:3}"
    fi
    if [[ "$2" == *ipaddress* ]]; then
        printf '172.28.0.2\n'
    fi
    exit 0
fi
if [[ "${1:-}" == */local_domain_acceptance.py ]]; then
    report=""
    mode=http
    while (($#)); do
        case "$1" in
            --report) report=$2; shift 2 ;;
            --sse-only) mode=sse; shift ;;
            *) shift ;;
        esac
    done
    if [[ "$mode" == sse ]]; then
        printf '{"stage":"g1","status":"PASS","checks":{"sse_first_frame_ms":"1","sse_total_ms":"1001"}}\n' >"$report"
    else
        printf '{"stage":"g1","status":"PASS","checks":{"browser_homepage":"HTTP 200"}}\n' >"$report"
    fi
    printf '{"stage":"g1","status":"PASS"}\n'
    exit 0
fi
if [[ "${1:-}" == - ]]; then
    exec "$REAL_PYTHON" "$@"
fi
exit 0
MOCK

for mock in "$task_bin/docker" "$task_bin/openssl" "$task_bin/certutil" \
    "$task_bin/curl" "$task_bin/python-task"; do
    chmod +x -- "$mock"
done
task_chromium="$task_bin/chromium"
: >"$task_chromium"
chmod +x -- "$task_chromium"

export PATH="$task_bin:$PATH"
export DOCKER_LOG="$task_log"
export OPENSSL_LOG="$task_test_root/openssl.log"
export CERTUTIL_LOG="$task_test_root/certutil.log"
export CURL_LOG="$task_test_root/curl.log"
export APP_IMAGE='newshub:test'
export NGINX_IMAGE='nginx:test'
export MOCK_IMAGE_SHA='0123456789abcdef0123456789abcdef01234567'
export PYTHON_BIN="$task_bin/python-task"
export REAL_PYTHON="$PROJECT_ROOT/backend/venv/bin/python"
export CHROMIUM_EXECUTABLE="$task_chromium"
export TMPDIR="$task_temp"

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
output="$("$SMOKE_SCRIPT")"
[[ "$output" == *'Dry run only'* ]] || fail 'default invocation did not stay in dry-run mode.'
assert_no_docker_calls
[[ ! -s "$OPENSSL_LOG" ]] || fail 'dry run unexpectedly invoked OpenSSL.'

expect_exit 2 "$SMOKE_SCRIPT" --root "$task_test_root"
expect_exit 2 "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha bad
expect_exit 2 "$SMOKE_SCRIPT" --stage invalid
expect_exit 3 "$SMOKE_SCRIPT" --stage g2 --execute
assert_no_docker_calls

expect_exit 2 env TMPDIR=relative "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
expect_exit 2 env TMPDIR=/ "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
expect_exit 2 env TMPDIR="$PROJECT_ROOT" "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
assert_no_docker_calls

: >"$DOCKER_LOG"
expect_exit 3 env MOCK_NGINX_MISSING=1 "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
if rg -q 'pull([[:space:]]|$)' "$DOCKER_LOG"; then
    fail 'the smoke attempted to pull the missing Nginx image.'
fi
if find "$task_temp" -mindepth 1 -maxdepth 1 -type d -name 'newshub-local-domain.*' -print -quit | grep -q .; then
    fail 'missing-image NOT_RUN created a temporary smoke or report directory.'
fi

: >"$DOCKER_LOG"
expect_exit 3 env MOCK_APP_MISSING=1 "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
if rg -q 'compose.*(config|run|up)' "$DOCKER_LOG"; then
    fail 'an unavailable application image reached Compose execution.'
fi

: >"$DOCKER_LOG"
expect_exit 2 env MOCK_IMAGE_SHA='ffffffffffffffffffffffffffffffffffffffff' \
    "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
rg -q 'org.opencontainers.image.revision' "$DOCKER_LOG" \
    || fail 'the smoke did not inspect the app image revision label.'
if rg -q 'compose.*(config|run|up)' "$DOCKER_LOG"; then
    fail 'an app revision mismatch reached Compose execution.'
fi

: >"$CERTUTIL_LOG"
export DASHSCOPE_CODING_API_KEY='local-test-secret-marker'
home_before="${HOME:-}"
"$REAL_PYTHON" - "$PROJECT_ROOT/scripts/deploy/local_domain_acceptance.py" \
    "$task_test_root/task-browser-home" "$task_test_root/test-ca.pem" <<'PY'
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('local_domain_acceptance', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
task_browser_home = Path(sys.argv[2])
task_browser_home.mkdir()
ca_cert = Path(sys.argv[3])
ca_cert.write_text('synthetic test certificate\n', encoding='utf-8')
module._new_nss_database(task_browser_home, ca_cert)
PY
[[ "${HOME:-}" == "$home_before" ]] || fail 'isolated browser profile setup changed the caller HOME.'
[[ "$(wc -l <"$CERTUTIL_LOG")" -eq 2 ]] || fail 'the mocked NSS helper did not call certutil for database setup and CA import.'
rg -q "HOME=$task_test_root/task-browser-home API_KEY_PRESENT=$" "$CERTUTIL_LOG" \
    || fail 'certutil inherited the caller home or an unrelated Provider environment variable.'
"$REAL_PYTHON" - "$SMOKE_SCRIPT" <<'PY'
import ast
import sys
from pathlib import Path

line = next(
    line for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
    if line.startswith('seed_code=')
)
seed_code = ast.literal_eval(line.split('=', 1)[1])
compile(seed_code, '<local-domain-fixture-seed>', 'exec')
flow_expression = seed_code.split('flow=', 1)[1].split('; news,_=', 1)[0]
flow = eval(flow_expression, {'__builtins__': {'chr': chr}})
assert '```mermaid\nflowchart TD' in flow
assert 'Fixture article' in flow and 'Mermaid flow' in flow
PY

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
output="$("$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA")" \
    || fail 'mocked execute smoke did not complete successfully.'
[[ "$output" == *'G1 local-domain smoke PASS'* ]] || fail 'mocked execute did not report G1 PASS.'
[[ "$output" == *'report.json'* ]] || fail 'the smoke did not report its JSON artifact path.'
rg -q 'compose.*down.*--volumes.*--remove-orphans' "$DOCKER_LOG" \
    || fail 'the smoke did not clean its unique Compose project and volumes.'
! rg -q '(^|[[:space:]])pull([[:space:]]|$)' "$DOCKER_LOG" \
    || fail 'the smoke attempted an implicit Docker pull.'
rg -q 'nginx.conf:/etc/nginx/conf.d/default.conf:ro|nginx.conf' "$DOCKER_LOG" \
    || fail 'Nginx config-test commands were not exercised.'
rg -q 'rand -hex 32' "$OPENSSL_LOG" || fail 'the smoke did not create an ephemeral test-only key.'
[[ ! -s "$CURL_LOG" ]] || fail 'the shell smoke invoked curl outside its acceptance helper.'
if find "$task_temp" -mindepth 1 -maxdepth 1 -type d -name 'newshub-local-domain.*' ! -name 'newshub-local-domain-report-*' -print -quit | grep -q .; then
    fail 'the smoke did not clean its exact temporary work directory.'
fi
report_path="$(printf '%s\n' "$output" | sed -n 's/.*report //p' | tail -n 1)"
[[ -f "$report_path" ]] || fail 'the report artifact was not retained outside the cleaned work directory.'
"$REAL_PYTHON" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8")); assert report["cleanup_status"] == "PASS" and report["status"] == "PASS" and report["image_revision"] == sys.argv[2] and report["nginx_image_id"] == "sha256:local-mock-image" and report["nginx_repo_digests"] == ["nginx@sha256:mock"] and report["nginx_version"] == "nginx version: nginx/1.30.5"' "$report_path" "$MOCK_IMAGE_SHA" \
    || fail 'the final report did not record the image revision and cleanup result.'

printf 'local-domain smoke argument/resource tests passed (Docker/OpenSSL/certutil/curl/browser are stubbed).\n'
