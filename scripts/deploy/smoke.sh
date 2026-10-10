#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
EXECUTE=0
BASE_URL=""
EXPECTED_MODE=""
CA_CERT=""
LOCAL_DOMAIN=0
IMAGE=""
SHA=""

usage() {
    cat <<'EOF'
Usage: smoke.sh [--execute] [--base-url HTTPS-URL --expected-mode read_only|full [--cacert FILE]]
                [--local-domain --image IMAGE --sha 40-HEX-SHA]

The default is a no-network dry run. HTTP checks only request readiness and capabilities.
--local-domain delegates the isolated TLS/browser work to local-domain-smoke.sh.
EOF
}

fail() {
    printf 'smoke: %s\n' "$1" >&2
    exit 2
}

while (($#)); do
    case "$1" in
        --execute) EXECUTE=1; shift ;;
        --base-url) (($# >= 2)) || fail '--base-url requires a value.'; BASE_URL=$2; shift 2 ;;
        --expected-mode) (($# >= 2)) || fail '--expected-mode requires a value.'; EXPECTED_MODE=$2; shift 2 ;;
        --cacert) (($# >= 2)) || fail '--cacert requires a value.'; CA_CERT=$2; shift 2 ;;
        --local-domain) LOCAL_DOMAIN=1; shift ;;
        --image) (($# >= 2)) || fail '--image requires a value.'; IMAGE=$2; shift 2 ;;
        --sha) (($# >= 2)) || fail '--sha requires a value.'; SHA=$2; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

if ((!EXECUTE)); then
    if ((LOCAL_DOMAIN)); then
        printf 'Dry run only: would delegate isolated G1 checks to local-domain-smoke.sh; no Docker, browser, or network calls.\n'
    else
        printf 'Dry run only: would make read-only readiness/capabilities requests; no network calls.\n'
    fi
    exit 0
fi

if ((LOCAL_DOMAIN)); then
    [[ -z "$BASE_URL" && -z "$EXPECTED_MODE" && -z "$CA_CERT" ]] \
        || fail '--local-domain cannot be combined with --base-url, --expected-mode, or --cacert.'
    [[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--local-domain requires --sha with 40 hexadecimal characters.'
    [[ -n "$IMAGE" ]] || fail '--local-domain requires --image.'
    exec "$SCRIPT_DIR/local-domain-smoke.sh" --execute --stage g1 --image "$IMAGE" --sha "${SHA,,}"
fi

[[ -n "$BASE_URL" && -n "$EXPECTED_MODE" ]] || fail '--execute requires --base-url and --expected-mode.'
[[ "$EXPECTED_MODE" == read_only || "$EXPECTED_MODE" == full ]] || fail '--expected-mode must be read_only or full.'
[[ -z "$IMAGE" && -z "$SHA" ]] || fail '--image/--sha are only valid with --local-domain.'
if [[ -n "$CA_CERT" ]]; then
    [[ -f "$CA_CERT" && ! -L "$CA_CERT" ]] || fail '--cacert must name an existing regular file.'
fi

python3 - "$BASE_URL" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1]
try:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or '').lower()
    port = parsed.port
except ValueError:
    raise SystemExit('smoke: --base-url is malformed.')
if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
    raise SystemExit('smoke: --base-url must not contain credentials, query, or fragment.')
if parsed.path not in ('', '/') or not hostname:
    raise SystemExit('smoke: --base-url must be an origin without a path.')
if parsed.scheme == 'https':
    if port not in (None, 443):
        raise SystemExit('smoke: HTTPS base URL must use the standard port.')
elif not (parsed.scheme == 'http' and hostname in ('127.0.0.1', 'localhost') and port is not None):
    raise SystemExit('smoke: only HTTPS origins or explicit loopback HTTP test origins are allowed.')
PY

command -v curl >/dev/null 2>&1 || fail 'curl is unavailable.'
curl_args=(--fail --silent --show-error --max-time 10 --proto '=https,http')
if [[ -n "$CA_CERT" ]]; then
    curl_args+=(--cacert "$CA_CERT")
fi
BASE_URL="${BASE_URL%/}"
curl "${curl_args[@]}" "$BASE_URL/api/health/ready/" >/dev/null \
    || fail 'read-only readiness request failed.'
capabilities="$(curl "${curl_args[@]}" "$BASE_URL/api/capabilities/")" \
    || fail 'read-only capabilities request failed.'
printf '%s' "$capabilities" | python3 -c '
import json
import sys
try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit("smoke: capabilities response is not valid JSON.")
expected = sys.argv[1]
if not isinstance(payload, dict) or payload.get("site_mode") != expected:
    raise SystemExit("smoke: site mode did not match the expected mode.")
features = payload.get("features")
if not isinstance(features, dict):
    raise SystemExit("smoke: capabilities features are missing.")
for name in ("news", "keyword_search"):
    feature = features.get(name)
    if not isinstance(feature, dict) or feature.get("enabled") is not True:
        raise SystemExit("smoke: public news/keyword capability is unavailable.")
print("PASS: read-only readiness and capabilities checks matched the expected mode.")
' "$EXPECTED_MODE"
