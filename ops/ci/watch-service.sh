#!/usr/bin/env bash
set -Eeuo pipefail

# Installs ONLY this user's NewsHub health timer. No sudo, no global units,
# no network listener, no access to production Docker projects or databases.
CI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DATA_DIR="${CI_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/newshub-ci}"
ACTION="${1:-install}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE="$UNIT_DIR/newshub-ci-watch.service"
TIMER="$UNIT_DIR/newshub-ci-watch.timer"
MARKER="# Managed by NewsHub ops/ci/watch-service.sh"

fail() { printf 'newshub-ci watch setup: %s\n' "$*" >&2; exit 2; }

case "$ACTION" in
    install)
        command -v systemctl >/dev/null 2>&1 || fail "systemd required"
        command -v python3 >/dev/null 2>&1 || fail "python3 required"
        [[ -d "$DATA_DIR" ]] || fail "Runner is not yet installed; run manage.sh install"
        mkdir -p -- "$UNIT_DIR"
        for unit in "$SERVICE" "$TIMER"; do
            if [[ -f "$unit" ]] && ! grep -Fxq "$MARKER" "$unit"; then
                fail "Unmanaged unit already exists: $unit"
            fi
        done
        # Escape percent specifiers and quote-sensitive paths in systemd files
        # rather than allowing a malformed or unintended ExecStart.
        for path in "$CI_DIR" "$DATA_DIR"; do
            [[ "$path" != *%* && "$path" != *'"'* && "$path" != *$'\n'* ]] \
                || fail "unsupported CI path for systemd unit"
        done
        [[ "$DATA_DIR" == /* ]] || fail "CI_DATA_DIR must be absolute"
        PYTHON="$(command -v python3)"
        {
            printf '%s\n' "$MARKER"
            cat <<'UNIT'
[Unit]
Description=NewsHub self-hosted CI health guard

[Service]
Type=oneshot
TimeoutStartSec=120
NoNewPrivileges=true
UNIT
            printf 'Environment="CI_DATA_DIR=%s"\n' "$DATA_DIR"
            printf 'ExecStart=%s "%s/watch.py"\n' "$PYTHON" "$CI_DIR"
        } > "$SERVICE"
        {
            printf '%s\n' "$MARKER"
            cat <<'UNIT'
[Unit]
Description=NewsHub CI boot and periodic health check

[Timer]
OnStartupSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Unit=newshub-ci-watch.service

[Install]
WantedBy=timers.target
UNIT
        } > "$TIMER"
        systemctl --user daemon-reload
        systemctl --user enable --now newshub-ci-watch.timer
        printf 'newshub-ci watch: user timer enabled (2m after login/boot, then every 5m).\n'
        if command -v loginctl >/dev/null 2>&1; then
            LINGER="$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)"
            if [[ "$LINGER" != yes ]]; then
                printf 'For recovery before logging into desktop: sudo loginctl enable-linger "%s"\n' "$USER"
            fi
        fi
        ;;
    uninstall)
        command -v systemctl >/dev/null 2>&1 || fail "systemd required"
        systemctl --user disable --now newshub-ci-watch.timer 2>/dev/null || true
        for unit in "$SERVICE" "$TIMER"; do
            if [[ -f "$unit" ]]; then
                grep -Fxq "$MARKER" "$unit" || fail "Unmanaged unit exists: $unit"
                rm -f -- "$unit"
            fi
        done
        systemctl --user daemon-reload
        printf 'newshub-ci watch: user timer disabled. No lingering policy changed.\n'
        ;;
    status)
        systemctl --user status newshub-ci-watch.timer --no-pager || true
        ;;
    *)
        fail "Usage: bash ops/ci/watch-service.sh [install|uninstall|status]"
        ;;
esac
