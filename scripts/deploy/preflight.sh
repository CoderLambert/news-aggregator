#!/usr/bin/env bash

# Read-only production preflight for the fixed NewsHub host. This script never
# changes DNS, connects to SSH unless explicitly requested, or reads local env
# files. External probes are bounded and their output is restricted to public
# DNS/TLS data or the explicitly allowlisted SSH snapshot below.

DOMAIN='news.lambert.host'
APEX='lambert.host'
EXPECTED_IPV4=''
OFFLINE=0
USE_SSH=0

usage() {
  printf '%s\n' \
    'Usage: scripts/deploy/preflight.sh [--offline] [--ssh] [--expected-ipv4 ADDRESS]' \
    '  --offline                 Do not invoke network tools; report external checks as NOT_RUN.' \
    '  --ssh                     Opt in to a bounded, read-only `ssh tencent` snapshot.' \
    '  --expected-ipv4 ADDRESS   Compare news.lambert.host A records with a verified public IPv4.'
}

while (($#)); do
  case "$1" in
    --offline)
      OFFLINE=1
      shift
      ;;
    --ssh)
      USE_SSH=1
      shift
      ;;
    --expected-ipv4)
      if (($# < 2)); then
        printf '%s\n' 'preflight: --expected-ipv4 requires an address' >&2
        usage >&2
        exit 2
      fi
      EXPECTED_IPV4=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'preflight: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

is_public_ipv4() {
  local address=$1 octet part
  local -a octets

  [[ $address =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || return 1
  IFS='.' read -r -a octets <<< "$address"
  ((${#octets[@]} == 4)) || return 1

  for octet in "${octets[@]}"; do
    ((${#octet} <= 3)) || return 1
    ((${#octet} == 1 || ${octet:0:1} != 0)) || return 1
    ((10#$octet <= 255)) || return 1
  done

  local a=$((10#${octets[0]}))
  local b=$((10#${octets[1]}))
  local c=$((10#${octets[2]}))

  # Exclude private, loopback, link-local, shared, documentation, benchmark,
  # multicast, and other non-globally-routable IPv4 ranges.
  ((a != 0 && a != 10 && a != 127 && a < 224)) || return 1
  ((a != 100 || b < 64 || b > 127)) || return 1
  ((a != 169 || b != 254)) || return 1
  ((a != 172 || b < 16 || b > 31)) || return 1
  ((a != 192 || b != 168)) || return 1
  ((a != 192 || b != 0 || c != 0)) || return 1
  ((a != 192 || b != 0 || c != 2)) || return 1
  ((a != 192 || b != 88 || c != 99)) || return 1
  ((a != 198 || (b != 18 && b != 19))) || return 1
  ((a != 198 || b != 51 || c != 100)) || return 1
  ((a != 203 || b != 0 || c != 113)) || return 1
  return 0
}

if [[ -n $EXPECTED_IPV4 ]] && ! is_public_ipv4 "$EXPECTED_IPV4"; then
  printf '%s\n' 'preflight: --expected-ipv4 must be a canonical, globally routable IPv4 address' >&2
  exit 2
fi

PASS_COUNT=0
BLOCKED_COUNT=0
NOT_RUN_COUNT=0

report() {
  local name=$1 status=$2 detail=${3:-} line
  printf '%s: %s\n' "$name" "$status"
  if [[ -n $detail ]]; then
    while IFS= read -r line; do
      [[ -n $line ]] && printf '  %s\n' "$line"
    done <<< "$detail"
  fi
  case "$status" in
    PASS) ((PASS_COUNT += 1)) ;;
    EXTERNAL_BLOCKED) ((BLOCKED_COUNT += 1)) ;;
    NOT_RUN) ((NOT_RUN_COUNT += 1)) ;;
  esac
}

finish() {
  printf 'Summary: PASS=%d EXTERNAL_BLOCKED=%d NOT_RUN=%d\n' \
    "$PASS_COUNT" "$BLOCKED_COUNT" "$NOT_RUN_COUNT"
  if ((BLOCKED_COUNT > 0)); then
    exit 1
  elif ((NOT_RUN_COUNT > 0)); then
    exit 2
  fi
  exit 0
}

if ((OFFLINE)); then
  printf 'NewsHub read-only preflight: %s (offline)\n' "$DOMAIN"
  report 'DNS NS lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS NS news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS A news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS AAAA news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS CNAME news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS CAA news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS CAA lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'DNS A expected IPv4 match' NOT_RUN '--offline selected; no network command invoked'
  report 'HTTPS news.lambert.host/' NOT_RUN '--offline selected; no network command invoked'
  report 'TLS SAN and validity news.lambert.host' NOT_RUN '--offline selected; no network command invoked'
  report 'SSH read-only snapshot tencent' NOT_RUN '--offline selected; SSH was not invoked'
  report 'Nginx server_name news.lambert.host' NOT_RUN '--offline selected; SSH was not invoked'
  report 'Nginx server_name git.lambert.host presence' NOT_RUN '--offline selected; SSH was not invoked'
  report 'SSH listeners 443 / 9527 / 5173' NOT_RUN '--offline selected; SSH was not invoked'
  report 'SSH certbot.timer' NOT_RUN '--offline selected; SSH was not invoked'
  finish
fi

printf 'NewsHub read-only preflight: %s\n' "$DOMAIN"
printf '%s\n' 'No DNS, SSH, Nginx, or server configuration is modified.'

DNS_LAST_RAW=''
DNS_LAST_STATUS='NOT_RUN'
DNS_A_RAW=''
DNS_A_STATUS='NOT_RUN'

query_dns() {
  local name=$1 type=$2 label=$3 required=$4 raw rc has_answer=0 answers=''

  if ! command -v dig >/dev/null 2>&1; then
    DNS_LAST_RAW=''
    DNS_LAST_STATUS='NOT_RUN'
    report "$label" NOT_RUN 'dig is unavailable'
    return
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    DNS_LAST_RAW=''
    DNS_LAST_STATUS='NOT_RUN'
    report "$label" NOT_RUN 'timeout command is unavailable'
    return
  fi

  if raw=$(timeout 10s dig +time=3 +tries=1 +noall +comments +answer "$type" "$name" 2>/dev/null); then
    rc=0
  else
    rc=$?
  fi
  DNS_LAST_RAW=$raw

  if ((rc != 0)); then
    DNS_LAST_STATUS='EXTERNAL_BLOCKED'
    if ((rc == 124)); then
      report "$label" EXTERNAL_BLOCKED 'DNS query timed out'
    else
      report "$label" EXTERNAL_BLOCKED 'DNS query failed'
    fi
    return
  fi
  if [[ $raw != *'status: NOERROR'* ]]; then
    DNS_LAST_STATUS='EXTERNAL_BLOCKED'
    report "$label" EXTERNAL_BLOCKED 'resolver returned a DNS error'
    return
  fi

  while IFS= read -r line; do
    if [[ $line == *" IN $type "* ]]; then
      has_answer=1
      answers+="${line}"$'\n'
    fi
  done <<< "$raw"

  if [[ $required == yes && $has_answer == 0 ]]; then
    DNS_LAST_STATUS='EXTERNAL_BLOCKED'
    report "$label" EXTERNAL_BLOCKED 'DNS response contains no required answer'
  else
    DNS_LAST_STATUS='PASS'
    if ((has_answer)); then
      report "$label" PASS "$answers"
    elif [[ $type == NS && $name == "$DOMAIN" ]]; then
      report "$label" PASS 'no delegated child zone; records inherit from lambert.host'
    elif [[ $type == AAAA ]]; then
      report "$label" PASS 'no AAAA record; IPv6 is not configured by this check'
    elif [[ $type == CNAME ]]; then
      report "$label" PASS 'no CNAME record'
    elif [[ $type == CAA ]]; then
      report "$label" PASS 'no CAA record at this name'
    else
      report "$label" PASS 'query completed with no answer'
    fi
  fi
}

query_dns "$APEX" NS 'DNS NS lambert.host' yes
query_dns "$DOMAIN" NS 'DNS NS news.lambert.host' no
query_dns "$DOMAIN" A 'DNS A news.lambert.host' yes
DNS_A_RAW=$DNS_LAST_RAW
DNS_A_STATUS=$DNS_LAST_STATUS
query_dns "$DOMAIN" AAAA 'DNS AAAA news.lambert.host' no
query_dns "$DOMAIN" CNAME 'DNS CNAME news.lambert.host' no
query_dns "$DOMAIN" CAA 'DNS CAA news.lambert.host' no
query_dns "$APEX" CAA 'DNS CAA lambert.host' no

if [[ -z $EXPECTED_IPV4 ]]; then
  report 'DNS A expected IPv4 match' NOT_RUN 'provide --expected-ipv4 from a verified source'
elif [[ $DNS_A_STATUS == NOT_RUN ]]; then
  report 'DNS A expected IPv4 match' NOT_RUN 'the A record query did not run'
elif [[ $DNS_A_STATUS == EXTERNAL_BLOCKED ]]; then
  report 'DNS A expected IPv4 match' EXTERNAL_BLOCKED 'the A record could not be verified'
else
  A_VALUES=()
  while IFS= read -r line; do
    if [[ $line == *' IN A '* ]]; then
      A_VALUES+=("${line##* }")
    fi
  done <<< "$DNS_A_RAW"
  if ((${#A_VALUES[@]} == 1)) && [[ ${A_VALUES[0]} == "$EXPECTED_IPV4" ]]; then
    report 'DNS A expected IPv4 match' PASS 'the single A answer matches the supplied verified IPv4'
  else
    report 'DNS A expected IPv4 match' EXTERNAL_BLOCKED 'DNS A answers do not exactly match the supplied verified IPv4'
  fi
fi

if ! command -v curl >/dev/null 2>&1; then
  report "HTTPS $DOMAIN/" NOT_RUN 'curl is unavailable'
elif ! command -v timeout >/dev/null 2>&1; then
  report "HTTPS $DOMAIN/" NOT_RUN 'timeout command is unavailable'
else
  if HTTP_STATUS=$(timeout 10s curl --disable --noproxy '*' --silent --show-error --output /dev/null \
    --connect-timeout 5 --max-time 10 --write-out '%{http_code}' \
    "https://$DOMAIN/" 2>/dev/null); then
    HTTP_RC=0
  else
    HTTP_RC=$?
  fi
  if ((HTTP_RC != 0)) || [[ ! $HTTP_STATUS =~ ^[0-9]{3}$ ]] || [[ $HTTP_STATUS == 000 ]]; then
    if ((HTTP_RC == 124)); then
      report "HTTPS $DOMAIN/" EXTERNAL_BLOCKED 'HTTPS request timed out or TLS verification failed'
    else
      report "HTTPS $DOMAIN/" EXTERNAL_BLOCKED 'HTTPS request failed or TLS verification failed'
    fi
  elif [[ $HTTP_STATUS == 2* || $HTTP_STATUS == 3* ]]; then
    report "HTTPS $DOMAIN/" PASS "HTTP status $HTTP_STATUS; redirects are reported without following them"
  else
    report "HTTPS $DOMAIN/" EXTERNAL_BLOCKED "HTTP status $HTTP_STATUS"
  fi
fi

openssl_certificate_info() {
  set -o pipefail
  timeout 10s openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" \
    -verify 10 -verify_return_error -verify_hostname "$DOMAIN" -showcerts \
    </dev/null 2>/dev/null | openssl x509 -noout -ext subjectAltName -dates 2>/dev/null
}

certificate_has_dns_san() {
  local text=$1 line rest san
  while IFS= read -r line; do
    rest=$line
    while [[ $rest == *DNS:* ]]; do
      rest=${rest#*DNS:}
      san=${rest%%,*}
      san=${san#"${san%%[![:space:]]*}"}
      san=${san%"${san##*[![:space:]]}"}
      if [[ $san == "$DOMAIN" || $san == '*.lambert.host' ]]; then
        return 0
      fi
    done
  done <<< "$text"
  return 1
}

if ! command -v openssl >/dev/null 2>&1; then
  report "TLS SAN and validity $DOMAIN" NOT_RUN 'openssl is unavailable'
elif ! command -v timeout >/dev/null 2>&1; then
  report "TLS SAN and validity $DOMAIN" NOT_RUN 'timeout command is unavailable'
else
  if CERT_INFO=$(openssl_certificate_info); then
    CERT_RC=0
  else
    CERT_RC=$?
  fi
  if ((CERT_RC != 0)); then
    if [[ -n $CERT_INFO ]]; then
      report "TLS SAN and validity $DOMAIN" EXTERNAL_BLOCKED $'certificate verification failed; parsed certificate fields follow\n'"$CERT_INFO"
    elif ((CERT_RC == 124)); then
      report "TLS SAN and validity $DOMAIN" EXTERNAL_BLOCKED 'TLS certificate query timed out'
    else
      report "TLS SAN and validity $DOMAIN" EXTERNAL_BLOCKED 'TLS certificate query or chain/hostname verification failed'
    fi
  elif [[ $CERT_INFO != *'notBefore='* || $CERT_INFO != *'notAfter='* ]]; then
    report "TLS SAN and validity $DOMAIN" EXTERNAL_BLOCKED 'certificate validity dates could not be parsed'
  elif ! certificate_has_dns_san "$CERT_INFO"; then
    report "TLS SAN and validity $DOMAIN" EXTERNAL_BLOCKED 'certificate SAN does not contain news.lambert.host or *.lambert.host'
  else
    report "TLS SAN and validity $DOMAIN" PASS "$CERT_INFO"
  fi
fi

extract_section() {
  local text=$1 wanted=$2 line inside=0 output=''
  while IFS= read -r line; do
    if [[ $line == "[$wanted]" ]]; then
      inside=1
      continue
    fi
    if [[ $line == \[*\] ]]; then
      inside=0
    fi
    if ((inside)); then
      output+="${line}"$'\n'
    fi
  done <<< "$text"
  printf '%s' "$output"
}

nginx_has_server_name() {
  local text=$1 wanted=$2 line names name
  while IFS= read -r line; do
    [[ $line == server_name[[:space:]]* ]] || continue
    names=${line#server_name}
    names=${names//;/ }
    for name in $names; do
      [[ $name == "$wanted" ]] && return 0
    done
  done <<< "$text"
  return 1
}

ss_status() {
  local section=$1 line state receive send local_address peer rest port
  local seen_9527=0 loopback_9527=0 other_9527=0 seen_443=0 seen_5173=0
  local state_443 state_9527 state_5173

  if [[ -z $section || $section == *'unavailable ('* ]]; then
    printf '%s\n' 'NOT_RUN'
    return
  fi
  while IFS= read -r line; do
    [[ $line == LISTEN* ]] || continue
    read -r state receive send local_address peer rest <<< "$line"
    port=${local_address##*:}
    case "$port" in
      443) seen_443=1 ;;
      5173) seen_5173=1 ;;
      9527)
        seen_9527=1
        case "$local_address" in
          127.*:9527|\[::1\]:9527) loopback_9527=1 ;;
          *) other_9527=1 ;;
        esac
        ;;
    esac
  done <<< "$section"

  if ((seen_443)); then state_443='LISTENING'; else state_443='NOT_LISTENING'; fi
  if ((seen_9527 == 0)); then
    state_9527='NOT_LISTENING'
  elif ((loopback_9527 == 1 && other_9527 == 0)); then
    state_9527='LOOPBACK_ONLY'
  else
    state_9527='NON_LOOPBACK_OR_MIXED'
  fi
  if ((seen_5173)); then state_5173='LISTENING'; else state_5173='NOT_LISTENING'; fi
  printf '443=%s 9527=%s 5173=%s\n' "$state_443" "$state_9527" "$state_5173"
}

if (( ! USE_SSH )); then
  report 'SSH read-only snapshot tencent' NOT_RUN '--ssh not selected'
  report 'Nginx server_name news.lambert.host' NOT_RUN '--ssh not selected'
  report 'Nginx server_name git.lambert.host presence' NOT_RUN '--ssh not selected'
  report 'SSH listeners 443 / 9527 / 5173' NOT_RUN '--ssh not selected'
  report 'SSH certbot.timer' NOT_RUN '--ssh not selected'
elif ! command -v ssh >/dev/null 2>&1; then
  report 'SSH read-only snapshot tencent' NOT_RUN 'ssh is unavailable'
  report 'Nginx server_name news.lambert.host' NOT_RUN 'SSH snapshot did not run'
  report 'Nginx server_name git.lambert.host presence' NOT_RUN 'SSH snapshot did not run'
  report 'SSH listeners 443 / 9527 / 5173' NOT_RUN 'SSH snapshot did not run'
  report 'SSH certbot.timer' NOT_RUN 'SSH snapshot did not run'
elif ! command -v timeout >/dev/null 2>&1; then
  report 'SSH read-only snapshot tencent' NOT_RUN 'timeout command is unavailable'
  report 'Nginx server_name news.lambert.host' NOT_RUN 'SSH snapshot did not run'
  report 'Nginx server_name git.lambert.host presence' NOT_RUN 'SSH snapshot did not run'
  report 'SSH listeners 443 / 9527 / 5173' NOT_RUN 'SSH snapshot did not run'
  report 'SSH certbot.timer' NOT_RUN 'SSH snapshot did not run'
else
  read -r -d '' SSH_REMOTE_COMMAND <<'REMOTE_COMMAND' || true
set +e
snapshot() {
  label=$1
  shift
  printf '\n[%s]\n' "$label"
  output=$("$@" 2>/dev/null)
  result=$?
  if [ -n "$output" ]; then
    printf '%s\n' "$output"
  elif [ "$result" -eq 0 ]; then
    printf '[no output]\n'
  else
    printf 'unavailable (exit %s)\n' "$result"
  fi
}
snapshot 'hostname' hostname
snapshot 'ip -brief address' ip -brief address
snapshot 'ss -lnt' ss -lnt
snapshot 'df -h' df -h
snapshot 'free -m' free -m
snapshot 'docker --version' docker --version
snapshot 'docker ps' docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
printf '\n[nginx filtered directives]\n'
if command -v nginx >/dev/null 2>&1; then
  nginx -T 2>/dev/null | awk '/^[[:space:]]*(server_name|listen|ssl_certificate)[[:space:]]/ { sub(/^[[:space:]]*/, ""); print; found=1 } END { if (!found) print "unavailable (no filtered directives)" }'
else
  printf 'unavailable (nginx is not installed)\n'
fi
snapshot 'systemctl is-active certbot.timer' systemctl is-active certbot.timer
REMOTE_COMMAND

  if SSH_OUTPUT=$(timeout 20s ssh -o BatchMode=yes -o ConnectTimeout=10 tencent "$SSH_REMOTE_COMMAND" 2>/dev/null); then
    SSH_RC=0
  else
    SSH_RC=$?
  fi
  if ((SSH_RC == 0)); then
    report 'SSH read-only snapshot tencent' PASS 'allowlisted read-only command completed; filtered output follows'
    while IFS= read -r line; do
      [[ -n $line ]] && printf '  %s\n' "$line"
    done <<< "$SSH_OUTPUT"

    NGINX_SECTION=$(extract_section "$SSH_OUTPUT" 'nginx filtered directives')
    if [[ $NGINX_SECTION == *'unavailable ('* || -z $NGINX_SECTION ]]; then
      report 'Nginx server_name news.lambert.host' NOT_RUN 'filtered Nginx configuration was unavailable'
      report 'Nginx server_name git.lambert.host presence' NOT_RUN 'filtered Nginx configuration was unavailable'
    else
      if nginx_has_server_name "$NGINX_SECTION" "$DOMAIN"; then
        report 'Nginx server_name news.lambert.host' PASS 'server_name directive is present'
      else
        report 'Nginx server_name news.lambert.host' EXTERNAL_BLOCKED 'server_name directive is absent from filtered Nginx output'
      fi
      if nginx_has_server_name "$NGINX_SECTION" 'git.lambert.host'; then
        report 'Nginx server_name git.lambert.host presence' PASS 'Gitea server_name directive is present'
      else
        report 'Nginx server_name git.lambert.host presence' EXTERNAL_BLOCKED 'Gitea server_name directive is absent from filtered Nginx output'
      fi
    fi

    SS_SECTION=$(extract_section "$SSH_OUTPUT" 'ss -lnt')
    SS_RESULT=$(ss_status "$SS_SECTION")
    if [[ $SS_RESULT == NOT_RUN ]]; then
      report 'SSH listeners 443 / 9527 / 5173' NOT_RUN 'ss -lnt output was unavailable'
    else
      if [[ $SS_RESULT == *'443=LISTENING'* && $SS_RESULT == *'9527=LOOPBACK_ONLY'* && $SS_RESULT == *'5173=NOT_LISTENING'* ]]; then
        report 'SSH listeners 443 / 9527 / 5173' PASS "$SS_RESULT"
      else
        report 'SSH listeners 443 / 9527 / 5173' EXTERNAL_BLOCKED "$SS_RESULT"
      fi
    fi

    CERTBOT_SECTION=$(extract_section "$SSH_OUTPUT" 'systemctl is-active certbot.timer')
    CERTBOT_STATE=${CERTBOT_SECTION//$'\n'/}
    if [[ $CERTBOT_STATE == active ]]; then
      report 'SSH certbot.timer' PASS 'systemctl reports active'
    elif [[ $CERTBOT_STATE == unavailable* || -z $CERTBOT_STATE ]]; then
      report 'SSH certbot.timer' NOT_RUN 'systemctl result was unavailable'
    else
      report 'SSH certbot.timer' EXTERNAL_BLOCKED "systemctl reports $CERTBOT_STATE"
    fi
  else
    if ((SSH_RC == 124)); then
      report 'SSH read-only snapshot tencent' EXTERNAL_BLOCKED 'SSH snapshot timed out'
    else
      report 'SSH read-only snapshot tencent' EXTERNAL_BLOCKED 'SSH snapshot failed; diagnostic output suppressed'
    fi
    report 'Nginx server_name news.lambert.host' NOT_RUN 'SSH snapshot did not complete'
    report 'Nginx server_name git.lambert.host presence' NOT_RUN 'SSH snapshot did not complete'
    report 'SSH listeners 443 / 9527 / 5173' NOT_RUN 'SSH snapshot did not complete'
    report 'SSH certbot.timer' NOT_RUN 'SSH snapshot did not complete'
  fi
fi

finish
