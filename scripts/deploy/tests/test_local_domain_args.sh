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
ARGV_VALIDATION_LOG="$task_test_root/acceptance-argv.log"
MODE_CAPTURE_LOG="$task_test_root/public-modes.log"
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
    elif [[ "$*" == *'.Config.User'* ]]; then
        printf '10001:10001\n'
    elif [[ "$*" == *'json .RepoDigests'* ]]; then
        printf '["nginx@sha256:mock"]\n'
    elif [[ "$*" == *'.Id'* ]]; then
        case "$image" in
            "$APP_IMAGE") printf '%s\n' "$MOCK_APP_IMAGE_ID" ;;
            "$NGINX_IMAGE") printf '%s\n' "$MOCK_NGINX_IMAGE_ID" ;;
            "$G2_CURL_IMAGE") printf '%s\n' "$MOCK_CURL_IMAGE_ID" ;;
            *) exit 1 ;;
        esac
    else
        printf 'sha256:mock\n'
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
        rg -F -q "image: \"$MOCK_APP_IMAGE_ID\"" "$compose_file" || exit 1
        rg -F -q "image: \"$MOCK_NGINX_IMAGE_ID\"" "$compose_file" || exit 1
        rg -F -q "NEWSHUB_LOCAL_DOMAIN_IMAGE_ID: \"$MOCK_APP_IMAGE_ID\"" "$compose_file" || exit 1
        ! rg -q '\$\{NEWSHUB_IMAGE|\$\{NGINX_IMAGE' "$compose_file" || exit 1
        ! rg -q '^    ports:' "$compose_file" || exit 1
        if [[ -n "${MOCK_MODE_CAPTURE_LOG:-}" ]]; then
            smoke_root="$(dirname -- "$compose_file")"
            for mode_entry in \
                "smoke_root:$smoke_root" \
                "acme_root:$smoke_root/acme" \
                "acme_well_known:$smoke_root/acme/.well-known" \
                "acme_challenge_dir:$smoke_root/acme/.well-known/acme-challenge" \
                "acme_challenge_file:$smoke_root/acme/.well-known/acme-challenge/newshub-local-test" \
                "legacy_asset:$smoke_root/site/assets/local-domain-legacy-12345678.js" \
                "fixture_bundle:$smoke_root/g2-fixtures.json" \
                "compose_env:$smoke_root/compose.env" \
                "ca_key:$smoke_root/certs/ca.key"; do
                mode_name="${mode_entry%%:*}"
                mode_path="${mode_entry#*:}"
                [[ -e "$mode_path" ]] || exit 1
                printf '%s=%s\n' "$mode_name" "$(stat -c '%a' -- "$mode_path")" \
                    >>"$MOCK_MODE_CAPTURE_LOG"
            done
        fi
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
    if [[ -n "${MOCK_MODE_CAPTURE_LOG:-}" ]]; then
        volume_mount=""
        for ((index = 1; index <= $#; index++)); do
            if [[ "${!index}" == --volume ]]; then
                next=$((index + 1))
                volume_mount="${!next}"
                break
            fi
        done
        fake_sse_source="${volume_mount%%:*}"
        [[ -f "$fake_sse_source" ]] || exit 1
        printf 'fake_sse=%s\n' "$(stat -c '%a' -- "$fake_sse_source")" \
            >>"$MOCK_MODE_CAPTURE_LOG"
    fi
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
if [[ "${1:-}" == */local_domain_fixtures.py ]]; then
    exec "$REAL_PYTHON" "$@"
fi
if [[ "${1:-}" == */local_domain_acceptance.py ]]; then
    acceptance_script=$1
    shift
    if [[ "${MOCK_VALIDATE_ACCEPTANCE_ARGS:-0}" == 1 ]]; then
        "$REAL_PYTHON" - "$acceptance_script" "$@" <<'PY'
import importlib.util, json, os, re, stat, sys
from pathlib import Path
script, *argv = sys.argv[1:]
spec = importlib.util.spec_from_file_location('local_domain_acceptance_shell_args', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
args = module._parse_args(argv)
if args.check_parents:
    if os.environ.get('MOCK_G2_PARENT_FAIL') == '1':
        report = {'stage': 'g2', 'status': 'FAIL', 'failure': {
            'stage': 'g2', 'check': 'g2.parent_identity',
            'exception_type': 'AcceptanceError',
        }}
        Path(args.report).write_text(json.dumps(report) + '\n', encoding='utf-8')
        Path(args.report).chmod(0o600)
        print(json.dumps(report))
        raise SystemExit(1)
    mode_log = os.environ.get('MOCK_MODE_CAPTURE_LOG')
    if mode_log:
        with open(mode_log, 'a', encoding='utf-8') as stream:
            stream.write(f'report_root={stat.S_IMODE(args.report.parent.stat().st_mode):o}\n')
    report = {'stage': 'g2', 'status': 'PASS', 'checks': {'parent_identity': 'PASS'}}
    Path(args.report).write_text(json.dumps(report) + '\n', encoding='utf-8')
    Path(args.report).chmod(0o600)
    print(json.dumps({
        'app_container_id': 'e' * 64,
        'gateway_container_id': 'd' * 64,
        'gateway_network_id': 'f' * 64,
        'gateway_ip': '172.28.0.2',
    }))
elif args.fixture_phase == 'seed':
    if os.environ.get('MOCK_G2_SEED_NO_REPORT_FAIL') == '1':
        raise SystemExit(1)
    if os.environ.get('MOCK_G2_SEED_FAIL') == '1':
        report = {'stage': 'g2', 'status': 'FAIL', 'failure': {
            'stage': 'g2', 'check': 'g2.fixture_seed',
            'exception_type': 'ImproperlyConfigured',
            'child_exception_type': 'ImproperlyConfigured',
        }}
        Path(args.report).write_text(json.dumps(report) + '\n', encoding='utf-8')
        Path(args.report).chmod(0o600)
        print(json.dumps(report))
        raise SystemExit(1)
    args.fixture_state.write_text('{"ok":true,"news_id":17,"users_seeded":2}\n', encoding='utf-8')
    args.fixture_state.chmod(0o600)
    mode_log = os.environ.get('MOCK_MODE_CAPTURE_LOG')
    if mode_log:
        with open(mode_log, 'a', encoding='utf-8') as stream:
            stream.write(f'fixture_state={stat.S_IMODE(args.fixture_state.stat().st_mode):o}\n')
    print('{"fixture_phase":"seed","status":"PASS"}')
else:
    if os.environ.get('MOCK_G2_CLEANUP_FAIL') == '1':
        report = {'stage': 'g2', 'status': 'FAIL', 'cleanup_status': 'FAIL'}
        Path(args.report).write_text(json.dumps(report) + '\n', encoding='utf-8')
        print(json.dumps(report))
        raise SystemExit(1)
    if args.sse_only:
        assert args.fixture_bundle is None and args.fixture_state is None and args.compose_project is None
        with open(os.environ['ARGV_VALIDATION_LOG'], 'a', encoding='utf-8') as stream:
            stream.write('g2-sse-only-has-no-account-or-compose-inputs\n')
    report = {'stage': args.stage, 'status': 'PASS', 'checks': {'sse_first_frame_ms': '1', 'sse_total_ms': '1001'}} if args.sse_only else {'stage': args.stage, 'status': 'PASS', 'checks': {'browser_homepage': 'HTTP 200'}}
    Path(args.report).write_text(json.dumps(report) + '\n', encoding='utf-8')
    print(json.dumps(report))
PY
        exit $?
    fi
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
export ARGV_VALIDATION_LOG
export APP_IMAGE='newshub:test'
export NGINX_IMAGE='nginx:test'
export G2_CURL_IMAGE='curlimages/curl:8.10.1'
export LOCAL_DOMAIN_CURL_IMAGE="$G2_CURL_IMAGE"
export MOCK_APP_IMAGE_ID="sha256:$(printf 'a%.0s' {1..64})"
export MOCK_NGINX_IMAGE_ID="sha256:$(printf 'b%.0s' {1..64})"
export MOCK_CURL_IMAGE_ID="sha256:$(printf 'c%.0s' {1..64})"
export MOCK_IMAGE_SHA='0123456789abcdef0123456789abcdef01234567'
export REAL_PYTHON="${PYTHON_BIN:-$PROJECT_ROOT/backend/venv/bin/python}"
export PYTHON_BIN="$task_bin/python-task"
export CHROMIUM_EXECUTABLE="$task_chromium"
export TMPDIR="$task_temp"

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
: >"$ARGV_VALIDATION_LOG"
output="$("$SMOKE_SCRIPT")"
[[ "$output" == *'Dry run only'* ]] || fail 'default invocation did not stay in dry-run mode.'
assert_no_docker_calls
[[ ! -s "$OPENSSL_LOG" ]] || fail 'dry run unexpectedly invoked OpenSSL.'

expect_exit 2 "$SMOKE_SCRIPT" --root "$task_test_root"
expect_exit 2 "$SMOKE_SCRIPT" --execute --image "$APP_IMAGE" --sha bad
expect_exit 2 "$SMOKE_SCRIPT" --stage invalid
output="$("$SMOKE_SCRIPT" --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA")"
[[ "$output" == *'stage G2'* && "$output" == *'Dry run only'* ]] \
    || fail 'G2 dry run did not remain no-resource.'
expect_exit 3 "$SMOKE_SCRIPT" --stage g3 --execute --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA"
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
    if line.lstrip().startswith('seed_code=')
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
"$REAL_PYTHON" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8")); assert report["cleanup_status"] == "PASS" and report["status"] == "PASS" and report["image_revision"] == sys.argv[2] and report["application_image_id"] == "sha256:" + "a" * 64 and report["application_image_user"] == "10001:10001" and report["nginx_image_id"] == "sha256:" + "b" * 64 and report["nginx_repo_digests"] == ["nginx@sha256:mock"] and report["nginx_version"] == "nginx version: nginx/1.30.5"' "$report_path" "$MOCK_IMAGE_SHA" \
    || fail 'the final report did not record the image revision and cleanup result.'

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
: >"$ARGV_VALIDATION_LOG"
: >"$MODE_CAPTURE_LOG"
output="$(env NEWSHUB_IMAGE='newshub:untrusted-override' MOCK_VALIDATE_ACCEPTANCE_ARGS=1 \
    MOCK_MODE_CAPTURE_LOG="$MODE_CAPTURE_LOG" \
    "$SMOKE_SCRIPT" --execute --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA")" \
    || fail 'mocked G2 smoke with real acceptance argument parsing did not complete successfully.'
[[ "$output" == *'G2 local-domain smoke PASS'* ]] || fail 'mocked execute did not report G2 PASS.'
[[ -s "$ARGV_VALIDATION_LOG" ]] || fail 'the shell-generated G2 SSE argv was not checked by the real parser.'
rg -q '^g2-sse-only-has-no-account-or-compose-inputs$' "$ARGV_VALIDATION_LOG" \
    || fail 'G2 SSE-only argv still carried account or Compose inputs.'
report_path="$(printf '%s\n' "$output" | sed -n 's/.*report //p' | tail -n 1)"
[[ -f "$report_path" ]] || fail 'the G2 report artifact was not retained outside the cleaned work directory.'
"$REAL_PYTHON" - "$report_path" "$MOCK_IMAGE_SHA" <<'PY'
import json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
assert report['cleanup_status'] == 'PASS' and report['status'] == 'PASS'
assert report['image_revision'] == sys.argv[2]
assert report['application_image'] == 'newshub:test'
assert report['application_image_id'] == 'sha256:' + 'a' * 64
assert report['nginx_image'] == 'nginx:test'
assert report['nginx_image_id'] == 'sha256:' + 'b' * 64
assert report['curl_image'] == 'curlimages/curl:8.10.1'
assert report['curl_image_id'] == 'sha256:' + 'c' * 64
PY
for expected_mode in \
    smoke_root=700 report_root=700 fixture_bundle=600 compose_env=600 ca_key=600 \
    acme_root=755 acme_well_known=755 acme_challenge_dir=755 acme_challenge_file=644 \
    legacy_asset=644 fake_sse=644; do
    rg -q "^${expected_mode}$" "$MODE_CAPTURE_LOG" \
        || fail "G2 fixture mode was not preserved: ${expected_mode%%=*}."
done
mode_matrix="$(LC_ALL=C sort "$MODE_CAPTURE_LOG" | paste -sd ' ' -)"
printf 'G2 fixture mode matrix: %s\n' "$mode_matrix"

for failure_case in parent seed; do
    : >"$DOCKER_LOG"
    : >"$OPENSSL_LOG"
    failure_output=""
    failure_exit=0
    if [[ "$failure_case" == parent ]]; then
        failure_output="$(env MOCK_VALIDATE_ACCEPTANCE_ARGS=1 MOCK_G2_PARENT_FAIL=1 \
            "$SMOKE_SCRIPT" --execute --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA" 2>&1)" || failure_exit=$?
        expected_check=g2.parent_identity
        expected_file=setup.json
    else
        failure_output="$(env MOCK_VALIDATE_ACCEPTANCE_ARGS=1 MOCK_G2_SEED_FAIL=1 \
            "$SMOKE_SCRIPT" --execute --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA" 2>&1)" || failure_exit=$?
        expected_check=g2.fixture_seed
        expected_file=seed.json
    fi
    [[ "$failure_exit" != 0 ]] || fail "G2 $failure_case failure was reported as PASS."
    [[ "$failure_output" == *'G2 local-domain smoke NOT PASS'* ]] \
        || fail "G2 $failure_case failure was hidden by the shell trap."
    failure_report_root="$(printf '%s\n' "$failure_output" | sed -n 's/.*report directory //p' | tail -n 1)"
    failure_report="$failure_report_root/$expected_file"
    [[ -f "$failure_report" ]] || fail "G2 $failure_case safe failure report was not retained."
    "$REAL_PYTHON" - "$failure_report" "$expected_check" <<'PY'
import json, stat, sys
from pathlib import Path
path = Path(sys.argv[1])
report = json.loads(path.read_text(encoding='utf-8'))
assert stat.S_IMODE(path.stat().st_mode) == 0o600
assert report['stage'] == 'g2' and report['status'] == 'FAIL'
assert report['cleanup_status'] == 'PASS'
assert report['failure']['check'] == sys.argv[2]
assert report['failure']['exception_type'] in ('AcceptanceError', 'ImproperlyConfigured')
PY
done

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
shell_failure_output=""
shell_failure_exit=0
shell_failure_output="$(env MOCK_VALIDATE_ACCEPTANCE_ARGS=1 MOCK_G2_SEED_NO_REPORT_FAIL=1 \
    "$SMOKE_SCRIPT" --execute --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA" 2>&1)" \
    || shell_failure_exit=$?
[[ "$shell_failure_exit" != 0 ]] || fail 'a seed command failure without a seed report was reported as PASS.'
[[ "$shell_failure_output" == *'G2 local-domain smoke NOT PASS'* ]] \
    || fail 'the shell trap hid a failure after setup passed.'
shell_failure_report_root="$(printf '%s\n' "$shell_failure_output" | sed -n 's/.*report directory //p' | tail -n 1)"
shell_failure_report="$shell_failure_report_root/setup.json"
[[ -f "$shell_failure_report" ]] || fail 'the passing setup report was not retained after a later shell failure.'
"$REAL_PYTHON" - "$shell_failure_report" <<'PY'
import json, stat, sys
from pathlib import Path
path = Path(sys.argv[1])
report = json.loads(path.read_text(encoding='utf-8'))
assert stat.S_IMODE(path.stat().st_mode) == 0o600
assert report['stage'] == 'g2' and report['status'] == 'FAIL'
assert report['cleanup_status'] == 'PASS'
assert report['failure'] == {
    'stage': 'g2', 'check': 'shell_failure', 'exception_type': 'ShellFailure',
}
PY

: >"$DOCKER_LOG"
: >"$OPENSSL_LOG"
g2_cleanup_output=""
g2_cleanup_exit=0
g2_cleanup_output="$(env MOCK_VALIDATE_ACCEPTANCE_ARGS=1 MOCK_G2_CLEANUP_FAIL=1 \
    "$SMOKE_SCRIPT" --execute --stage g2 --image "$APP_IMAGE" --sha "$MOCK_IMAGE_SHA" 2>&1)" || g2_cleanup_exit=$?
[[ "$g2_cleanup_exit" != 0 ]] || fail 'a G2 acceptance cleanup failure was reported as PASS by the shell trap.'
[[ "$g2_cleanup_output" == *'G2 local-domain smoke NOT PASS'* ]] \
    || fail 'the shell trap hid the G2 cleanup failure from its final status.'
report_root="$(printf '%s\n' "$g2_cleanup_output" | sed -n 's/.*report directory //p' | tail -n 1)"
report_path="$report_root/http-browser.json"
[[ -f "$report_path" ]] || fail 'the failed G2 cleanup report was not retained.'
"$REAL_PYTHON" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8")); assert report["cleanup_status"] == "FAIL" and report["status"] == "FAIL"' "$report_path" \
    || fail 'the shell trap overwrote cleanup_status FAIL or overall status FAIL.'

printf 'local-domain smoke argument/resource tests passed (Docker/OpenSSL/certutil/curl/browser are stubbed).\n'
