#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
PREFLIGHT="$ROOT_DIR/scripts/deploy/preflight.sh"
TMP_DIR=$(mktemp -d)
TIMEOUT_BIN=$(command -v timeout)
MOCK_SOURCE="$TMP_DIR/mock-source"
mkdir -p "$MOCK_SOURCE"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_contains() {
  local text=$1 expected=$2 message=${3:-"expected output to contain: $2"}
  [[ $text == *"$expected"* ]] || fail "$message"
}

assert_not_contains() {
  local text=$1 unexpected=$2 message=${3:-"unexpected output: $2"}
  [[ $text != *"$unexpected"* ]] || fail "$message"
}

assert_exit() {
  local expected=$1 actual=$2 label=$3
  [[ $expected == "$actual" ]] || fail "$label: expected exit $expected, got $actual"
}

cat > "$MOCK_SOURCE/dig" <<'MOCK_DIG'
#!/bin/bash
[[ -z ${MOCK_MARKER:-} ]] || printf 'dig\n' >> "$MOCK_MARKER"
[[ ${MOCK_DNS_FAIL:-0} == 1 ]] && exit 124
type=${@: -2:1}
name=${@: -1}
printf ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n'
case "$type:$name" in
  NS:lambert.host)
    printf 'lambert.host. 600 IN NS ns1.example.test.\n'
    ;;
  A:news.lambert.host)
    printf 'news.lambert.host. 600 IN A %s\n' "${MOCK_A_VALUE:-8.8.8.8}"
    ;;
  CAA:lambert.host)
    printf 'lambert.host. 600 IN CAA 0 issue "letsencrypt.org"\n'
    ;;
esac
MOCK_DIG

cat > "$MOCK_SOURCE/curl" <<'MOCK_CURL'
#!/bin/bash
[[ -z ${MOCK_MARKER:-} ]] || printf 'curl\n' >> "$MOCK_MARKER"
[[ ${1:-} == --disable && ${2:-} == --noproxy && ${3:-} == '*' ]] || exit 91
for arg in "$@"; do
  [[ $arg == -k || $arg == --insecure || $arg == -L || $arg == --location ]] && exit 90
done
[[ ${MOCK_HTTP_FAIL:-0} == 1 ]] && exit 28
printf '%s' "${MOCK_HTTP_STATUS:-200}"
MOCK_CURL

cat > "$MOCK_SOURCE/openssl" <<'MOCK_OPENSSL'
#!/bin/bash
subcommand=${1:-}
[[ -z ${MOCK_MARKER:-} ]] || printf 'openssl:%s\n' "$subcommand" >> "$MOCK_MARKER"
if [[ $subcommand == s_client ]]; then
  [[ ${MOCK_TLS_FAIL:-0} == 1 ]] && exit 124
  printf 'mock certificate chain\n'
  exit 0
fi
if [[ $subcommand == x509 ]]; then
  input=$(</dev/stdin)
  [[ -n $input ]] || exit 1
  if [[ ${MOCK_SAN_MISSING:-0} == 1 ]]; then
    printf 'X509v3 Subject Alternative Name:\n    DNS:else.lambert.host\n'
  else
    printf 'X509v3 Subject Alternative Name:\n    DNS:news.lambert.host, DNS:git.lambert.host\n'
  fi
  printf 'notBefore=Oct  1 00:00:00 2026 GMT\nnotAfter=Oct  1 00:00:00 2030 GMT\n'
  exit 0
fi
exit 91
MOCK_OPENSSL

cat > "$MOCK_SOURCE/ssh" <<'MOCK_SSH'
#!/bin/bash
[[ -z ${MOCK_MARKER:-} ]] || printf 'ssh\n' >> "$MOCK_MARKER"
[[ ${MOCK_SSH_FAIL:-0} == 1 ]] && exit 255
if [[ -n ${MOCK_MARKER:-} ]]; then
  printf 'ssh-args:' >> "$MOCK_MARKER"
  printf ' <%s>' "$@" >> "$MOCK_MARKER"
  printf '\n' >> "$MOCK_MARKER"
fi
cat <<'SNAPSHOT'
[hostname]
news-vm
[ip -brief address]
eth0 UP 10.0.0.2/24
[ss -lnt]
State Recv-Q Send-Q Local Address:Port Peer Address:Port
LISTEN 0 4096 0.0.0.0:443 0.0.0.0:*
LISTEN 0 4096 127.0.0.1:9527 0.0.0.0:*
[df -h]
Filesystem Size Used Avail Use% Mounted on
/dev/vda1 100G 10G 90G 10% /
[free -m]
total used free shared buff/cache available
16000 1000 12000 10 3000 14500
[docker --version]
Docker version 27.0.0
[docker ps]
news-app Up 3 hours 127.0.0.1:9527->9527/tcp
[nginx filtered directives]
listen 443 ssl;
server_name news.lambert.host;
ssl_certificate /etc/letsencrypt/live/news/fullchain.pem;
server_name git.lambert.host;
[systemctl is-active certbot.timer]
active
SNAPSHOT
MOCK_SSH

chmod +x "$MOCK_SOURCE/dig" "$MOCK_SOURCE/curl" "$MOCK_SOURCE/openssl" "$MOCK_SOURCE/ssh"

make_path() {
  local path_dir=$1
  shift
  mkdir -p "$path_dir"
  ln -sf "$TIMEOUT_BIN" "$path_dir/timeout"
  ln -sf "$(command -v cat)" "$path_dir/cat"
  local utility
  for utility in "$@"; do
    cp "$MOCK_SOURCE/$utility" "$path_dir/$utility"
    chmod +x "$path_dir/$utility"
  done
}

run_preflight() {
  local expected_rc=$1 label=$2
  shift 2
  local output rc
  if output=$(MOCK_MARKER="$TMP_DIR/commands" PATH="$TEST_PATH" /bin/bash "$PREFLIGHT" "$@" 2>"$TMP_DIR/stderr"); then
    rc=0
  else
    rc=$?
  fi
  if [[ $expected_rc != "$rc" ]]; then
    printf '%s\n' "$output" >&2
    [[ ! -s $TMP_DIR/stderr ]] || cat "$TMP_DIR/stderr" >&2
  fi
  assert_exit "$expected_rc" "$rc" "$label"
  RUN_OUTPUT=$output
}

DEFAULT_PATH="$TMP_DIR/default"
make_path "$DEFAULT_PATH" dig curl openssl ssh
TEST_PATH=$DEFAULT_PATH
: > "$TMP_DIR/commands"
run_preflight 2 'offline checks return NOT_RUN' --offline
assert_contains "$RUN_OUTPUT" 'Summary: PASS=0 EXTERNAL_BLOCKED=0 NOT_RUN=15'
assert_contains "$RUN_OUTPUT" 'DNS A news.lambert.host: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'SSH read-only snapshot tencent: NOT_RUN'
[[ ! -s $TMP_DIR/commands ]] || fail '--offline invoked a network command'

run_preflight 2 'successful public probes still report unprovided checks as NOT_RUN'
assert_contains "$RUN_OUTPUT" 'DNS NS lambert.host: PASS'
assert_contains "$RUN_OUTPUT" 'DNS A news.lambert.host: PASS'
assert_contains "$RUN_OUTPUT" 'HTTPS news.lambert.host/: PASS'
assert_contains "$RUN_OUTPUT" 'TLS SAN and validity news.lambert.host: PASS'
assert_contains "$RUN_OUTPUT" 'DNS A expected IPv4 match: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'SSH read-only snapshot tencent: NOT_RUN'
assert_not_contains "$RUN_OUTPUT" ': EXTERNAL_BLOCKED'
assert_not_contains "$(<"$TMP_DIR/commands")" 'ssh'
assert_not_contains "$(<"$TMP_DIR/commands")" 'openssl:-k'

: > "$TMP_DIR/commands"
run_preflight 0 'complete mocked report passes' --expected-ipv4 8.8.8.8 --ssh
assert_contains "$RUN_OUTPUT" 'DNS A expected IPv4 match: PASS'
assert_contains "$RUN_OUTPUT" 'SSH read-only snapshot tencent: PASS'
assert_contains "$RUN_OUTPUT" 'Nginx server_name news.lambert.host: PASS'
assert_contains "$RUN_OUTPUT" 'Nginx server_name git.lambert.host presence: PASS'
assert_contains "$RUN_OUTPUT" 'SSH listeners 443 / 9527 / 5173: PASS'
assert_contains "$RUN_OUTPUT" 'SSH certbot.timer: PASS'
assert_contains "$(<"$TMP_DIR/commands")" 'ssh-args: <-o> <BatchMode=yes> <-o> <ConnectTimeout=10> <tencent>'
assert_contains "$(<"$TMP_DIR/commands")" 'nginx -T 2>/dev/null | awk'
assert_not_contains "$RUN_OUTPUT" ': EXTERNAL_BLOCKED'

MOCK_A_VALUE=1.1.1.1 run_preflight 1 'mismatched expected IPv4 is blocked' --expected-ipv4 8.8.8.8
assert_contains "$RUN_OUTPUT" 'DNS A expected IPv4 match: EXTERNAL_BLOCKED'

MOCK_DNS_FAIL=1 run_preflight 1 'DNS timeout is externally blocked' --expected-ipv4 8.8.8.8
assert_contains "$RUN_OUTPUT" 'DNS NS lambert.host: EXTERNAL_BLOCKED'
assert_contains "$RUN_OUTPUT" 'DNS A expected IPv4 match: EXTERNAL_BLOCKED'

MOCK_TLS_FAIL=1 run_preflight 1 'TLS timeout is externally blocked'
assert_contains "$RUN_OUTPUT" 'TLS SAN and validity news.lambert.host: EXTERNAL_BLOCKED'

MOCK_SAN_MISSING=1 run_preflight 1 'certificate SAN mismatch is externally blocked'
assert_contains "$RUN_OUTPUT" 'certificate SAN does not contain news.lambert.host'

for invalid_ipv4 in '127.0.0.1' '192.168.1.2' '203.0.113.10' '999.1.1.1' '1.2.3' '01.2.3.4'; do
  : > "$TMP_DIR/commands"
  if MOCK_MARKER="$TMP_DIR/commands" PATH="$TEST_PATH" /bin/bash "$PREFLIGHT" --expected-ipv4 "$invalid_ipv4" >"$TMP_DIR/stdout" 2>"$TMP_DIR/stderr"; then
    fail "invalid expected IPv4 was accepted: $invalid_ipv4"
  else
    rc=$?
  fi
  assert_exit 2 "$rc" "invalid IPv4 $invalid_ipv4"
  [[ ! -s $TMP_DIR/commands ]] || fail "invalid IPv4 $invalid_ipv4 triggered a network command"
done

: > "$TMP_DIR/commands"
if MOCK_MARKER="$TMP_DIR/commands" PATH="$TEST_PATH" /bin/bash "$PREFLIGHT" --unknown >"$TMP_DIR/stdout" 2>"$TMP_DIR/stderr"; then
  fail 'unknown option was accepted'
else
  rc=$?
fi
assert_exit 2 "$rc" 'unknown option'
[[ ! -s $TMP_DIR/commands ]] || fail 'unknown option triggered a network command'

PATH_NO_NETWORK="$TMP_DIR/no-network"
make_path "$PATH_NO_NETWORK"
TEST_PATH=$PATH_NO_NETWORK
run_preflight 2 'missing dig, curl, and openssl produce NOT_RUN'
assert_contains "$RUN_OUTPUT" 'DNS NS lambert.host: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'dig is unavailable'
assert_contains "$RUN_OUTPUT" 'HTTPS news.lambert.host/: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'curl is unavailable'
assert_contains "$RUN_OUTPUT" 'TLS SAN and validity news.lambert.host: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'openssl is unavailable'

PATH_NO_CURL="$TMP_DIR/no-curl"
make_path "$PATH_NO_CURL" dig openssl
TEST_PATH=$PATH_NO_CURL
run_preflight 2 'missing curl produces NOT_RUN'
assert_contains "$RUN_OUTPUT" 'HTTPS news.lambert.host/: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'curl is unavailable'

PATH_NO_OPENSSL="$TMP_DIR/no-openssl"
make_path "$PATH_NO_OPENSSL" dig curl
TEST_PATH=$PATH_NO_OPENSSL
run_preflight 2 'missing openssl produces NOT_RUN'
assert_contains "$RUN_OUTPUT" 'TLS SAN and validity news.lambert.host: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'openssl is unavailable'

PATH_NO_SSH="$TMP_DIR/no-ssh"
make_path "$PATH_NO_SSH" dig curl openssl
TEST_PATH=$PATH_NO_SSH
run_preflight 2 'missing ssh after explicit opt-in produces NOT_RUN' --ssh
assert_contains "$RUN_OUTPUT" 'SSH read-only snapshot tencent: NOT_RUN'
assert_contains "$RUN_OUTPUT" 'ssh is unavailable'

printf '%s\n' 'All preflight tests passed.'
