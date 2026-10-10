#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

EXECUTE=0
IMAGE=""
SHA=""
STAGE="g1"
NGINX_IMAGE="${NGINX_IMAGE:-nginx:stable-alpine}"
NGINX_IMAGE_ID=""
NGINX_REPO_DIGESTS=""
NGINX_VERSION=""
CHROMIUM_EXECUTABLE="${CHROMIUM_EXECUTABLE:-/usr/bin/chromium}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/backend/venv/bin/python}"
task_smoke_root=""
task_report_root=""
task_compose_file=""
task_compose_env=""
task_compose_project=""
task_compose_started=0
task_fake_server_id=""
task_cleanup_failed=0
TASK_TMPDIR=""

usage() {
    cat <<'EOF'
Usage: local-domain-smoke.sh [--execute] [--image IMAGE] [--sha 40-HEX-SHA]
                             [--stage g1|g2] [--nginx-image IMAGE]
                             [--chromium-executable ABSOLUTE-PATH]

Without --execute, this validates arguments and prints a no-resource dry-run plan.
Stage g2 is reserved and returns NOT_RUN until it has a separate implementation contract.
The smoke never pulls images. Preload the selected app and Nginx images first.
EOF
}

fail() {
    printf 'local-domain-smoke: %s\n' "$1" >&2
    exit 2
}

not_run() {
    printf 'NOT_RUN: %s\n' "$1" >&2
    exit 3
}

cleanup() {
    local status=$?
    local report_path="${task_report_root:+$task_report_root/report.json}"
    trap - EXIT INT TERM

    if [[ -n "$task_fake_server_id" ]]; then
        docker rm -f "$task_fake_server_id" >/dev/null 2>&1 || task_cleanup_failed=1
    fi
    if ((task_compose_started)); then
        if ! docker compose --project-name "$task_compose_project" \
            --file "$task_compose_file" --env-file "$task_compose_env" \
            down --volumes --remove-orphans >/dev/null 2>&1; then
            task_cleanup_failed=1
        fi
    fi
    if [[ -n "$task_smoke_root" && -d "$task_smoke_root" ]]; then
        if [[ "$(dirname -- "$task_smoke_root")" == "$TASK_TMPDIR" \
            && "$(basename -- "$task_smoke_root")" == newshub-local-domain.* ]]; then
            rm -rf -- "$task_smoke_root" || task_cleanup_failed=1
        else
            printf 'local-domain-smoke: refused to remove an unexpected smoke path.\n' >&2
            task_cleanup_failed=1
        fi
    fi

    if [[ -n "$report_path" && -f "$report_path" && -x "$PYTHON_BIN" ]]; then
        if ! "$PYTHON_BIN" -c 'import json,sys; from pathlib import Path; path=Path(sys.argv[1]); report=json.loads(path.read_text(encoding="utf-8")); report["cleanup_status"]="PASS" if sys.argv[2] == "0" else "FAIL"; report["status"]="FAIL" if sys.argv[2] != "0" else report.get("status", "FAIL"); path.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")' \
            "$report_path" "$task_cleanup_failed" >/dev/null 2>&1; then
            task_cleanup_failed=1
            status=1
        fi
    fi

    if ((task_cleanup_failed)); then
        printf 'local-domain-smoke: cleanup failed for one or more smoke-owned resources.\n' >&2
        if ((status == 0)); then
            status=1
        fi
    fi
    if ((status == 0)); then
        printf 'G1 local-domain smoke PASS; app revision %s; Nginx image %s; report %s\n' \
            "$SHA" "$NGINX_IMAGE ($NGINX_IMAGE_ID)" "$report_path"
    elif [[ -n "$task_report_root" ]]; then
        printf 'G1 local-domain smoke NOT PASS; app revision %s; Nginx image %s; report directory %s\n' \
            "$SHA" "$NGINX_IMAGE ($NGINX_IMAGE_ID)" "$task_report_root" >&2
    fi
    exit "$status"
}

while (($#)); do
    case "$1" in
        --execute)
            EXECUTE=1
            shift
            ;;
        --image)
            (($# >= 2)) || fail '--image requires a value.'
            IMAGE=$2
            shift 2
            ;;
        --sha)
            (($# >= 2)) || fail '--sha requires a value.'
            SHA=$2
            shift 2
            ;;
        --stage)
            (($# >= 2)) || fail '--stage requires a value.'
            STAGE=$2
            shift 2
            ;;
        --nginx-image)
            (($# >= 2)) || fail '--nginx-image requires a value.'
            NGINX_IMAGE=$2
            shift 2
            ;;
        --chromium-executable)
            (($# >= 2)) || fail '--chromium-executable requires a value.'
            CHROMIUM_EXECUTABLE=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ "$STAGE" == g1 || "$STAGE" == g2 ]] || fail '--stage must be g1 or g2.'
if [[ "$STAGE" == g2 ]]; then
    not_run 'G2 browser account/session checks are not implemented; use the G1 stage only.'
fi

if ((!EXECUTE)); then
    if [[ -z "$IMAGE" && -z "$SHA" ]]; then
        printf 'Dry run only: stage G1, default Nginx image %s; no Docker, certificate, browser, or filesystem resources created.\n' "$NGINX_IMAGE"
        exit 0
    fi
    [[ -n "$IMAGE" && -n "$SHA" ]] || fail 'dry-run arguments must include --image and --sha together.'
    [[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must be exactly 40 hexadecimal characters.'
    SHA="${SHA,,}"
    printf 'Dry run only: would verify image %s at revision %s with Nginx image %s; no resources created.\n' \
        "$IMAGE" "$SHA" "$NGINX_IMAGE"
    exit 0
fi

[[ -n "$IMAGE" ]] || fail '--execute requires --image.'
[[ -n "$SHA" ]] || fail '--execute requires --sha.'
[[ -n "$NGINX_IMAGE" ]] || fail 'Nginx image must not be empty.'
[[ "$IMAGE" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] || fail '--image must be a single valid image reference.'
[[ "$NGINX_IMAGE" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] || fail '--nginx-image must be a single valid image reference.'
[[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must be exactly 40 hexadecimal characters.'
SHA="${SHA,,}"

TASK_TMPDIR="${TMPDIR:-/tmp}"
[[ "$TASK_TMPDIR" == /* ]] || fail 'TMPDIR must be an absolute path.'
[[ -d "$TASK_TMPDIR" ]] || fail 'TMPDIR must already exist as a directory.'
TASK_TMPDIR="$(realpath -e -- "$TASK_TMPDIR")" || fail 'TMPDIR could not be resolved.'
[[ "$TASK_TMPDIR" != / ]] || fail 'TMPDIR must not resolve to /.'
[[ "$TASK_TMPDIR" != "$PROJECT_ROOT" && "$TASK_TMPDIR" != "$PROJECT_ROOT/"* ]] \
    || fail 'TMPDIR must be outside the source tree.'
[[ "$TASK_TMPDIR" != *$'\n'* && "$TASK_TMPDIR" != *$'\r'* ]] || fail 'TMPDIR must not contain line breaks.'

command -v docker >/dev/null 2>&1 || not_run 'Docker CLI is unavailable.'
docker compose version >/dev/null 2>&1 || not_run 'Docker Compose v2 is unavailable.'
command -v openssl >/dev/null 2>&1 || not_run 'OpenSSL is unavailable.'
command -v certutil >/dev/null 2>&1 || not_run 'certutil is unavailable for the isolated Chromium NSS profile.'
command -v curl >/dev/null 2>&1 || not_run 'curl is unavailable.'
[[ -x "$PYTHON_BIN" ]] || not_run 'the selected Python interpreter is unavailable; set PYTHON_BIN to backend/venv/bin/python.'
[[ "$CHROMIUM_EXECUTABLE" == /* && -x "$CHROMIUM_EXECUTABLE" ]] \
    || not_run 'Chromium must be an executable absolute path; set CHROMIUM_EXECUTABLE or use --chromium-executable.'
if ! "$PYTHON_BIN" -c 'import importlib.metadata; assert importlib.metadata.version("playwright") == "1.62.0"' >/dev/null 2>&1; then
    not_run 'the selected Python interpreter must provide Playwright 1.62.0.'
fi

if ! NGINX_IMAGE_ID="$(docker image inspect --format='{{.Id}}' "$NGINX_IMAGE" 2>/dev/null)"; then
    not_run "Nginx image $NGINX_IMAGE is not present locally; preload it explicitly (the smoke never pulls images)."
fi
[[ -n "$NGINX_IMAGE_ID" ]] || not_run "Nginx image $NGINX_IMAGE has no local image ID."
NGINX_REPO_DIGESTS="$(docker image inspect --format='{{json .RepoDigests}}' "$NGINX_IMAGE" 2>/dev/null)" \
    || fail 'could not inspect the selected Nginx image RepoDigests.'
if ! docker image inspect --format='{{.Id}}' "$IMAGE" >/dev/null 2>&1; then
    not_run "application image $IMAGE is not present locally; build or preload the fixed-revision image first."
fi
IMAGE_REVISION="$(docker image inspect --format='{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE" 2>/dev/null)" \
    || fail 'could not inspect the requested application image revision label.'
[[ "$IMAGE_REVISION" =~ ^[[:xdigit:]]{40}$ ]] || fail 'application image revision label is missing or invalid.'
IMAGE_REVISION="${IMAGE_REVISION,,}"
[[ "$IMAGE_REVISION" == "$SHA" ]] || fail 'application image revision label does not match --sha.'
NGINX_VERSION="$(docker run --rm --pull=never --network=none "$NGINX_IMAGE" nginx -v 2>&1)" \
    || fail 'could not read the selected local Nginx version.'

task_smoke_root="$(mktemp -d "$TASK_TMPDIR/newshub-local-domain.XXXXXX")" \
    || fail 'could not create the isolated smoke directory.'
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ "$(dirname -- "$task_smoke_root")" == "$TASK_TMPDIR" ]] || fail 'mktemp returned an unexpected smoke path.'
[[ ! -L "$task_smoke_root" && -d "$task_smoke_root" ]] || fail 'smoke path is not a real directory.'
task_report_root="$(mktemp -d "$TASK_TMPDIR/newshub-local-domain-report-${SHA}.XXXXXX")" \
    || fail 'could not create the smoke report directory.'
[[ "$(dirname -- "$task_report_root")" == "$TASK_TMPDIR" ]] || fail 'mktemp returned an unexpected report path.'
task_compose_project="newshub-local-g1-$$-$RANDOM"
task_compose_file="$task_smoke_root/compose.yaml"
task_compose_env="$task_smoke_root/compose.env"
mkdir -p -- "$task_smoke_root/certs" "$task_smoke_root/acme/.well-known/acme-challenge" \
    "$task_smoke_root/site"
secret_key="$(openssl rand -hex 32)" || fail 'could not create an ephemeral smoke-only application key.'
[[ "$secret_key" =~ ^[[:xdigit:]]{64}$ ]] || fail 'OpenSSL returned an invalid ephemeral key.'
printf 'NEWSHUB_IMAGE=%s\nNGINX_IMAGE=%s\nDJANGO_SECRET_KEY=%s\n' \
    "$IMAGE" "$NGINX_IMAGE" "$secret_key" >"$task_compose_env"
unset secret_key

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$task_smoke_root/certs/ca.key" \
    -out "$task_smoke_root/certs/ca.crt" -days 2 -subj '/CN=NewsHub Isolated Local Test CA' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' >/dev/null 2>&1 \
    || fail 'could not create the temporary test CA.'

create_leaf_certificate() {
    local name=$1
    local common_name=$2
    local san=$3
    local certificate_dir="$task_smoke_root/certs"
    local extension_file="$certificate_dir/$name.ext"
    printf 'subjectAltName = DNS:%s\nextendedKeyUsage = serverAuth\n' "$san" >"$extension_file"
    openssl req -newkey rsa:2048 -nodes -keyout "$certificate_dir/$name.key" \
        -out "$certificate_dir/$name.csr" -subj "/CN=$common_name" >/dev/null 2>&1 \
        || fail "could not create the temporary $name certificate request."
    openssl x509 -req -in "$certificate_dir/$name.csr" \
        -CA "$certificate_dir/ca.crt" -CAkey "$certificate_dir/ca.key" \
        -CAcreateserial -out "$certificate_dir/$name.crt" -days 2 -sha256 \
        -extfile "$extension_file" >/dev/null 2>&1 \
        || fail "could not sign the temporary $name certificate."
}

create_leaf_certificate server news.lambert.host news.lambert.host
create_leaf_certificate wrong-san wrong.invalid wrong.invalid
printf 'newshub-local-acme-fixture\n' > \
    "$task_smoke_root/acme/.well-known/acme-challenge/newshub-local-test"

sed \
    -e 's#/etc/letsencrypt/live/news.lambert.host/fullchain.pem#/etc/nginx/test-certs/server.crt#g' \
    -e 's#/etc/letsencrypt/live/news.lambert.host/privkey.pem#/etc/nginx/test-certs/server.key#g' \
    "$PROJECT_ROOT/deploy/nginx/news.lambert.host.conf" >"$task_smoke_root/nginx.conf"
cat >>"$task_smoke_root/nginx.conf" <<'EOF'

server {
    listen 4443 ssl;
    server_name wrong.invalid;
    ssl_certificate /etc/nginx/test-certs/wrong-san.crt;
    ssl_certificate_key /etc/nginx/test-certs/wrong-san.key;
    return 200 "wrong-san-fixture";
}
EOF

docker run --rm --pull=never --network=none \
    --volume "$PROJECT_ROOT/deploy/nginx/news.lambert.host.bootstrap.conf:/etc/nginx/conf.d/default.conf:ro" \
    "$NGINX_IMAGE" nginx -t || fail 'isolated Nginx bootstrap template check failed.'
docker run --rm --pull=never --network=none \
    --volume "$task_smoke_root/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
    --volume "$PROJECT_ROOT/deploy/nginx/newshub-proxy.conf:/etc/nginx/snippets/newshub-proxy.conf:ro" \
    --volume "$task_smoke_root/certs:/etc/nginx/test-certs:ro" \
    "$NGINX_IMAGE" nginx -t || fail 'isolated Nginx production template check failed.'

"$PROJECT_ROOT/scripts/deploy/export-static.sh" --execute --image "$IMAGE" --sha "$SHA" \
    --root "$task_smoke_root/site" || fail 'static export from the selected image failed.'
printf 'legacy-asset-fixture\n' >"$task_smoke_root/site/assets/local-domain-legacy-12345678.js"

yaml_quote() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//\$/\$\$}
    value=${value//$'\n'/\\n}
    value=${value//$'\r'/\\r}
    printf '"%s"' "$value"
}

bind_mount() {
    local source=$1
    local target=$2
    printf '      - type: bind\n        source: %s\n        target: %s\n        read_only: true\n' \
        "$(yaml_quote "$source")" "$(yaml_quote "$target")"
}

{
    cat <<'EOF'
x-smoke-environment: &smoke-environment
  DJANGO_ENV: production
  DJANGO_DEBUG: "0"
  DJANGO_SECRET_KEY: "${DJANGO_SECRET_KEY}"
  WAITRESS_TRUSTED_PROXY: 127.0.0.1
  WAITRESS_HOST: 127.0.0.1
  WAITRESS_PORT: "9527"
  WAITRESS_THREADS: "4"
  WAITRESS_CONN_LIMIT: "1000"
  DJANGO_DB_PATH: /var/lib/newshub/db/db.sqlite3
  PUBLIC_SITE_MODE: read_only
  PUBLIC_SIGNUP_ENABLED: "0"
  PUBLIC_AI_ENABLED: "0"
  CHATGPT_PLAN_USAGE_ENABLED: "0"
  CHATGPT_AUTH_MODE: disabled
  CRAWLER_SCHEDULER_ENABLED: "0"
  CRAWL_RUN_ON_START: "0"
  SEARCH_INDEX_ENABLED: "0"
  RUN_MAIN: "true"

services:
  gateway:
    image: "${NGINX_IMAGE}"
    pull_policy: never
    command: ["nginx", "-g", "daemon off;"]
    volumes:
EOF
    bind_mount "$task_smoke_root/nginx.conf" /etc/nginx/conf.d/default.conf
    bind_mount "$PROJECT_ROOT/deploy/nginx/newshub-proxy.conf" /etc/nginx/snippets/newshub-proxy.conf
    bind_mount "$task_smoke_root/certs" /etc/nginx/test-certs
    bind_mount "$task_smoke_root/site" /srv/newshub
    bind_mount "$task_smoke_root/acme" /var/www/certbot
    cat <<'EOF'
    networks:
      isolated:
        aliases:
          - news.lambert.host

  migrate:
    image: "${NEWSHUB_IMAGE}"
    pull_policy: never
    entrypoint: ["python", "/app/scripts/docker-migrate.py"]
    environment: *smoke-environment
    network_mode: none
    volumes:
      - db-data:/var/lib/newshub/db
    restart: "no"

  app:
    image: "${NEWSHUB_IMAGE}"
    pull_policy: never
    environment: *smoke-environment
    network_mode: service:gateway
    depends_on:
      gateway:
        condition: service_started
    volumes:
      - db-data:/var/lib/newshub/db
    restart: "no"

networks:
  isolated:
    internal: true

volumes:
  db-data: {}
EOF
} >"$task_compose_file"

docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" config --quiet \
    || fail 'isolated smoke Compose configuration is invalid.'

task_compose_started=1
docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" run --rm migrate \
    || fail 'temporary database migration failed.'
docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" up -d gateway app \
    || fail 'isolated Nginx and Waitress services failed to start.'

ready=0
for _attempt in {1..30}; do
    if docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
        --env-file "$task_compose_env" exec -T app python -c \
        'import urllib.request; req=urllib.request.Request("http://127.0.0.1:9527/api/health/ready/", headers={"Host":"news.lambert.host"}); urllib.request.urlopen(req, timeout=3)' \
        >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
((ready)) || fail 'temporary app did not pass its database readiness probe.'

seed_code="from django.utils import timezone; from api.models import Category, News, Source; category,_=Category.objects.get_or_create(name='NewsHub Local Domain Fixture', defaults={'slug':'newshub-local-domain-fixture'}); source,_=Source.objects.get_or_create(name='NewsHub Local Domain Fixture', defaults={'url':'https://fixture.invalid/news'}); flow=\"## Isolated article flow\\n\\n\"+chr(96)*3+\"mermaid\\nflowchart TD\\n  news[Fixture article] --> diagram[Mermaid flow]\\n\"+chr(96)*3+\"\\n\"; news,_=News.objects.get_or_create(url='https://fixture.invalid/newshub-local-domain-g1', defaults={'title':'NewshubLocalDomainG1Fixture','content':'isolated smoke fixture','full_content':flow,'full_content_fetch_status':'success','publish_time':timezone.now(),'source':source,'category':category}); print(news.pk)"
if ! docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" exec -T app python /app/backend/manage.py shell -c "$seed_code" \
    >"$task_smoke_root/seed.stdout" 2>"$task_smoke_root/seed.stderr"; then
    fail 'could not seed the isolated news fixture.'
fi
news_id="$(tail -n 1 "$task_smoke_root/seed.stdout" | tr -d '\r')"
[[ "$news_id" =~ ^[1-9][0-9]*$ ]] || fail 'the isolated news fixture returned an invalid ID.'

gateway_id="$(docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" ps -q gateway)" || fail 'could not find the isolated Nginx container.'
[[ -n "$gateway_id" ]] || fail 'the isolated Nginx container ID is empty.'
gateway_ip="$(docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$gateway_id")" \
    || fail 'could not inspect the isolated Nginx address.'
gateway_ip="$("$PYTHON_BIN" -c 'import ipaddress,sys; address=ipaddress.ip_address(sys.argv[1]); assert address.version == 4; print(address)' "$gateway_ip")" \
    || fail 'the isolated Nginx address is not IPv4.'

mkdir -p -- "$task_report_root"
http_report="$task_report_root/http-browser.json"
sse_report="$task_report_root/sse.json"
if ! "$PYTHON_BIN" "$PROJECT_ROOT/scripts/deploy/local_domain_acceptance.py" \
    --gateway-ip "$gateway_ip" --ca-cert "$task_smoke_root/certs/ca.crt" \
    --work-dir "$task_report_root" --news-id "$news_id" \
    --chromium-executable "$CHROMIUM_EXECUTABLE" --image-revision "$SHA" \
    --nginx-image "$NGINX_IMAGE" --report "$http_report"; then
    printf 'local-domain-smoke: HTTP/browser checks failed; report: %s\n' "$http_report" >&2
    exit 1
fi

docker compose --project-name "$task_compose_project" --file "$task_compose_file" \
    --env-file "$task_compose_env" stop app >/dev/null \
    || fail 'could not stop the isolated app before the fake SSE upstream.'
FAKE_SSE_SCRIPT="$task_smoke_root/fake_sse.py"
cat >"$FAKE_SSE_SCRIPT" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith('/api/news/') or not self.path.endswith('/chat/'):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(b'data: first-frame\n\n')
        self.wfile.flush()
        proxy_headers = {
            'host': self.headers.get('Host'),
            'x_forwarded_proto': self.headers.get('X-Forwarded-Proto'),
            'x_forwarded_for': self.headers.get('X-Forwarded-For'),
            'forwarded': self.headers.get('Forwarded'),
            'x_forwarded_host': self.headers.get('X-Forwarded-Host'),
            'x_forwarded_port': self.headers.get('X-Forwarded-Port'),
        }
        self.wfile.write(
            b'data: proxy-headers=' + json.dumps(proxy_headers, sort_keys=True).encode('utf-8') + b'\n\n'
        )
        self.wfile.flush()
        time.sleep(1)
        self.wfile.write(b'data: final-frame\n\n')
        self.wfile.flush()

    def log_message(self, *_args):
        pass

HTTPServer(('127.0.0.1', 9527), Handler).serve_forever()
PY
task_fake_server_id="$(docker run -d --rm --pull=never --network "container:$gateway_id" \
    --volume "$FAKE_SSE_SCRIPT:/tmp/newshub-fake-sse.py:ro" \
    "$IMAGE" python /tmp/newshub-fake-sse.py)" \
    || fail 'could not start the isolated fake SSE upstream.'
[[ -n "$task_fake_server_id" ]] || fail 'fake SSE server did not return its container ID.'

fake_ready=0
for _attempt in {1..20}; do
    if docker exec "$task_fake_server_id" python -c \
        'import socket; socket.create_connection(("127.0.0.1",9527), timeout=1).close()' \
        >/dev/null 2>&1; then
        fake_ready=1
        break
    fi
    sleep 0.1
done
((fake_ready)) || fail 'fake SSE upstream did not listen on the isolated loopback port.'
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/deploy/local_domain_acceptance.py" \
    --gateway-ip "$gateway_ip" --ca-cert "$task_smoke_root/certs/ca.crt" \
    --work-dir "$task_report_root" --sse-only --news-id "$news_id" --image-revision "$SHA" \
    --nginx-image "$NGINX_IMAGE" --report "$sse_report" \
    || fail 'isolated Nginx SSE first-frame timing check failed.'
docker rm -f "$task_fake_server_id" >/dev/null
task_fake_server_id=""

"$PYTHON_BIN" - "$http_report" "$sse_report" "$task_report_root/report.json" \
    "$IMAGE" "$SHA" "$NGINX_IMAGE" "$NGINX_IMAGE_ID" "$NGINX_REPO_DIGESTS" "$NGINX_VERSION" <<'PY'
import json
import sys
from pathlib import Path

http_result = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
sse_result = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
checks = {**http_result.get('checks', {}), **sse_result.get('checks', {})}
result = {
    'stage': 'g1',
    'status': 'PASS' if http_result.get('status') == 'PASS' and sse_result.get('status') == 'PASS' else 'FAIL',
    'cleanup_status': 'pending',
    'application_image': sys.argv[4],
    'image_revision': sys.argv[5],
    'nginx_image': sys.argv[6],
    'nginx_image_id': sys.argv[7],
    'nginx_repo_digests': json.loads(sys.argv[8]),
    'nginx_version': sys.argv[9],
    'checks': {
        'compose_config': 'PASS (docker compose config --quiet exit 0)',
        'nginx_bootstrap_config': 'PASS (nginx -t exit 0)',
        'nginx_production_config': 'PASS (nginx -t exit 0)',
        'static_export': 'PASS',
        'database_migration': 'PASS',
        'waitress_database_readiness': 'PASS',
        'fixture_seed': 'PASS',
        **checks,
    },
}
Path(sys.argv[3]).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
if result['status'] != 'PASS':
    raise SystemExit(1)
print(json.dumps(result, sort_keys=True))
PY
