#!/usr/bin/env python3
"""Conservative self-hosted CI recovery, designed for a user-systemd timer.

Never restarts a running Runner/DinD unless GitHub explicitly reports idle
and docker top confirms no Runner.Worker process. Read-only when GitHub API is
unavailable or a CI job may be running. No registration or production access.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = "CoderLambert/news-aggregator"
NAMES = {
    "runner": "omarchy-newshub",
    "runner-frontend": "omarchy-newshub-frontend",
}
PROJECT = "newshub-ci"
WINDOW_SECONDS = 6 * 3600
COOLDOWN_SECONDS = 15 * 60
PERSISTENT_FAILURES = 3
OFFLINE_GRACE_SECONDS = 5 * 60


def log(message: str) -> None:
    print(f"newshub-ci-watch: {message}", flush=True)


def command(argv: list[str], *, timeout: int = 20) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            check=False, env=os.environ,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 125, ""


def docker_state(service: str) -> tuple[str | None, str | None, str]:
    # Use Docker's exact Compose labels rather than referencing a mutable Git
    # checkout. The monitor is installed outside the repository so it remains
    # functional if the user switches branches or moves the source tree.
    rc, cid = command([
        "docker", "ps", "--all", "--quiet",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={service}",
    ])
    if rc or not cid:
        return None, None, "missing"
    cid = cid.splitlines()[0].strip()
    rc, result = command(["docker", "inspect", "--format", "{{json .State}}", cid])
    if rc:
        return cid, None, "unknown"
    try:
        state = json.loads(result)
        health = state.get("Health") or {}
        return cid, str(state.get("Status", "unknown")), health.get("Status", "none")
    except (TypeError, ValueError):
        return cid, None, "unknown"


def github_runners() -> dict[str, dict] | None:
    rc, data = command(["gh", "api", f"repos/{REPO}/actions/runners?per_page=100"], timeout=25)
    if rc:
        return None
    try:
        return {
            item["name"]: item
            for item in json.loads(data)["runners"]
            if item.get("name") in NAMES.values()
        }
    except (TypeError, ValueError, KeyError):
        return None


def worker_activity(cid: str | None) -> bool | None:
    if cid is None:
        return False
    rc, output = command(["docker", "top", cid], timeout=12)
    if rc:
        return None
    return "Runner.Worker" in output


def read_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, state: dict) -> None:
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def eligible(state: dict, name: str, now: int, *, grace: bool) -> tuple[bool, str]:
    item = state.setdefault(name, {})
    window_start = int(item.get("window_start", now))
    if now - window_start >= WINDOW_SECONDS or window_start > now:
        item.clear()
        window_start = now
    item.setdefault("window_start", window_start)
    item.setdefault("attempts", 0)
    item.setdefault("last_attempt", 0)
    item.setdefault("first_unhealthy", now)
    if int(item["attempts"]) >= PERSISTENT_FAILURES:
        return False, f"recovery cap reached ({PERSISTENT_FAILURES} attempts / 6h)"
    if now - int(item["last_attempt"]) < COOLDOWN_SECONDS:
        return False, "waiting for 15-minute cooldown"
    if grace and now - int(item["first_unhealthy"]) < OFFLINE_GRACE_SECONDS:
        return False, "waiting for 5-minute consecutive unhealthy evidence"
    return True, ""


def consider_restart(
    service: str,
    cid: str | None,
    status: str | None,
    health: str,
    remote: dict[str, dict] | None,
    state: dict,
    now: int,
    backend_worker: bool | None,
) -> None:
    name = NAMES.get(service)
    remote_row = remote.get(name) if (remote is not None and name) else None
    remote_online = bool(remote_row and remote_row.get("status") == "online")
    remote_busy = bool(remote_row and remote_row.get("busy"))
    is_backend_docker = service == "docker"
    is_running = status == "running"
    good = is_running and (health in ("healthy", "none"))

    if service in NAMES and remote_online:
        if remote_busy:
            state.setdefault(service, {}).pop("first_unhealthy", None)
            log(f"{service}: GitHub Online / Busy; never restart an active CI task")
            return
        if good:
            state.setdefault(service, {}).pop("first_unhealthy", None)
            log(f"{service}: GitHub Online / Idle, container {health}")
            return
    elif is_backend_docker and good:
        state.setdefault(service, {}).pop("first_unhealthy", None)
        log("docker: DinD healthy")
        return

    if cid is None:
        log(f"{service}: no container; requires explicit manage.sh install/start")
        return

    # Docker's restart: unless-stopped can itself create an endless crash loop.
    # Once a container has been in Restarting state across two timer ticks,
    # stop THAT container and leave it for manual repair, rather than retrying.
    # A Restarting container is not running an active worker. For DinD, still
    # refuse to touch it if backend job activity is positive or unknown.
    if status == "restarting":
        record = state.setdefault(service, {})
        first = int(record.setdefault("first_unhealthy", now))
        if now - first < OFFLINE_GRACE_SECONDS:
            log(f"{service}: Docker crash loop observed; waiting for second check")
            return
        if (is_backend_docker and (remote is None
                or remote.get(NAMES["runner"], {}).get("busy")
                or backend_worker is not False)):
            log("docker: backend job may still be busy; crash loop not modified")
            return
        if not is_backend_docker and remote_busy:
            log(f"{service}: remote job marked Busy; crash loop not modified")
            return
        rc, _ = command(["docker", "stop", "--time", "20", cid], timeout=45)
        record["window_start"] = now
        record["attempts"] = PERSISTENT_FAILURES
        record["last_attempt"] = now
        log(f"{service}: crash-loop quarantine {'OK' if rc == 0 else 'FAILED'}; "
            "manual investigation required; no auto-retry for 6h")
        return

    # If it is still running, do not assume that a failing Docker healthcheck
    # means the workflow has stopped; require positive external idle evidence.
    if is_running or status == "restarting":
        if is_backend_docker:
            if remote is None or remote.get(NAMES["runner"]) is None:
                log("docker: GitHub state unavailable; cannot prove backend idle")
                return
            if remote[NAMES["runner"]].get("busy"):
                log("docker: backend is Busy; will not disrupt Docker during CI")
                return
            if backend_worker is not False:
                log("docker: local worker state unknown or active; no restart")
                return
        else:
            if remote_row is None:
                log(f"{service}: GitHub status unknown/unregistered; no forced restart")
                return
            if remote_busy:
                log(f"{service}: GitHub Busy; no forced restart")
                return
            local_worker = worker_activity(cid)
            if local_worker is not False:
                log(f"{service}: active worker or worker check unavailable; no restart")
                return
            if remote_online and health == "healthy":
                return
    elif is_backend_docker and backend_worker is not False:
        log("docker: local backend worker active/unknown; cannot start DinD")
        return

    # Only verified idle, unhealthy containers receive a delayed restart;
    # stopped containers may be started without registration-token access.
    safe, reason = eligible(state, service, now, grace=is_running)
    if not safe:
        log(f"{service}: {reason}")
        return

    argv = ["docker", "restart", "--time", "30", cid] if is_running else ["docker", "start", cid]
    state[service]["attempts"] += 1
    state[service]["last_attempt"] = now
    rc, _ = command(argv, timeout=55)
    log(f"{service}: {'restarted' if is_running else 'started'} attempt {state[service]['attempts']} / {PERSISTENT_FAILURES}: {'OK' if rc == 0 else 'FAILED'}")


def watch(data_dir: Path) -> int:
    if (data_dir / "maintenance-disabled").exists():
        log("manually stopped / maintenance-disabled; no automatic recovery")
        return 0
    if not (data_dir / "registration-token").exists():
        log("not installed yet; run manage.sh install")
        return 0
    os.environ["CI_DATA_DIR"] = str(data_dir)
    state_path = data_dir / "watch-state.json"
    state = read_state(state_path)
    now = int(time.time())

    rc, _ = command(["docker", "info"], timeout=10)
    if rc:
        log("host Docker daemon unavailable; will retry on next timer tick")
        return 0
    remote = github_runners()
    if remote is None:
        log("GitHub API unavailable: will not restart running CI containers")

    snapshots = {
        name: docker_state(name)
        for name in ("docker", "runner", "runner-frontend")
    }
    backend_cid, backend_status, _ = snapshots["runner"]
    backend_worker = (
        worker_activity(backend_cid) if backend_status == "running"
        else False
    )
    # DinD first: even a restarted offline backend listener requires a daemon.
    for service in ("docker", "runner", "runner-frontend"):
        cid, status, health = snapshots[service]
        consider_restart(service, cid, status, health, remote, state, now, backend_worker)
    write_state(state_path, state)
    return 0


def main() -> int:
    data_dir = Path(os.environ.get(
        "CI_DATA_DIR",
        str(Path.home() / ".local/share/newshub-ci"),
    )).expanduser()
    if not data_dir.is_absolute() or not data_dir.is_dir() or data_dir.is_symlink():
        log("invalid/missing CI_DATA_DIR; run manage.sh install first")
        return 2
    lock_path = data_dir / "watch.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("previous health check still running; skipping overlap")
            return 0
        return watch(data_dir)


if __name__ == "__main__":
    sys.exit(main())
