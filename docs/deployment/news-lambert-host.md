# `news.lambert.host` read-only production preflight

This procedure records evidence before and after a separately authorized DNS change. The script only reads public DNS and HTTPS/TLS state. It does not change DNS, SSH, Nginx, certificates, or server configuration. SSH is skipped unless an operator passes `--ssh`; that option runs only the allowlisted read-only snapshot described below. No local `.env` file is read or printed.

The target hostname is fixed as `news.lambert.host`; the parent zone is `lambert.host`. A successful local report does not by itself establish that the site has been deployed or that a public change is approved.

This implementation was validated offline with command mocks only. No live DNS, HTTP, TLS, or SSH probe was run, so current public-site state remains `NOT_RUN`. The hostname is currently unused per the project owner; the absence of a DNS record is a launch-time observation, not a blocker to local development.

## Run the preflight

First check the command-line and offline reporting path. This invocation makes no network calls and is expected to exit `2` because the external checks are `NOT_RUN`:

```bash
bash -n scripts/deploy/preflight.sh scripts/deploy/tests/test_preflight.sh
bash scripts/deploy/tests/test_preflight.sh
bash scripts/deploy/preflight.sh --offline
```

For public DNS and HTTPS/TLS checks, provide the IPv4 address only after verifying it from an authorized server console or trusted inventory. The script validates that the value is a canonical, globally routable IPv4 address and compares it with the single `news.lambert.host` A answer. It does not infer or discover the intended address.

```bash
: "${VERIFIED_PUBLIC_IPV4:?Set this from a verified source before running the network checks}"
scripts/deploy/preflight.sh --expected-ipv4 "$VERIFIED_PUBLIC_IPV4"
```

An operator may explicitly opt into the server snapshot:

```bash
scripts/deploy/preflight.sh --expected-ipv4 "$VERIFIED_PUBLIC_IPV4" --ssh
```

That option uses `ssh -o BatchMode=yes -o ConnectTimeout=10 tencent` with a 20-second overall timeout. The remote read-only commands are limited to `hostname`, `ip -brief address`, `ss -lnt`, `df -h`, `free -m`, `docker --version`, `docker ps` with only container name/status/ports, filtered `nginx -T` output containing only `server_name`, `listen`, and `ssl_certificate` directives, and `systemctl is-active certbot.timer`. The complete Nginx configuration, Docker environment, and container command fields are not emitted.

Each check is labeled `PASS`, `EXTERNAL_BLOCKED`, or `NOT_RUN`. Exit `0` means all checks passed, exit `1` means at least one external check is blocked, and exit `2` means no external check was blocked but at least one check was not run. Missing tools are `NOT_RUN`; DNS/TLS/network failures and mismatches are `EXTERNAL_BLOCKED`. No check result should be described as a deployment or production launch.

## Read-only evidence before and after a DNS change

Run the same commands immediately before and after an operator makes any approved DNS change. Save the outputs with the change record, excluding any shell history or unrelated environment values:

```bash
set -o pipefail
timeout 10s dig +time=3 +tries=1 NS lambert.host
timeout 10s dig +time=3 +tries=1 NS news.lambert.host
timeout 10s dig +time=3 +tries=1 A news.lambert.host
timeout 10s dig +time=3 +tries=1 AAAA news.lambert.host
timeout 10s dig +time=3 +tries=1 CNAME news.lambert.host
timeout 10s dig +time=3 +tries=1 CAA news.lambert.host
timeout 10s dig +time=3 +tries=1 CAA lambert.host
curl --disable --noproxy '*' --silent --show-error --output /dev/null --connect-timeout 5 --max-time 10 --write-out 'HTTP %{http_code}\n' https://news.lambert.host/
timeout 10s openssl s_client -connect news.lambert.host:443 -servername news.lambert.host -verify 10 -verify_return_error -verify_hostname news.lambert.host -showcerts </dev/null 2>/dev/null | openssl x509 -noout -ext subjectAltName -dates
```

Use `scripts/deploy/preflight.sh --ssh` for the bounded server-side snapshot and filtered Nginx/Gitea coexistence check. The script checks that the Nginx output contains `server_name news.lambert.host` and reports whether `server_name git.lambert.host` is present. It does not change or reload either virtual host. Server resource output is evidence for an operator to assess; the script does not invent disk or memory thresholds.

## DNS change target for a human change record

If a DNS change is later approved and the destination has been independently verified, the intended change is only:

- `news.lambert.host` A → the verified public IPv4, TTL `600`.
- Add an AAAA record only after the public IPv6 route, firewall, Nginx listener, and TLS path have all been validated end to end.
- Do not change the `lambert.host` apex, `git.lambert.host`, mail records, or nameserver delegation as part of this NewsHub change.

The repository contains no DNS-provider command for this procedure. The current authoritative DNS provider and destination address must be confirmed outside this report before any human executes a change. Re-run the read-only checks afterward and keep unresolved results marked `EXTERNAL_BLOCKED` or `NOT_RUN`.
