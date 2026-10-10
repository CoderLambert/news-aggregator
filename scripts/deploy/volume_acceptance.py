#!/usr/bin/env python3
"""Run the G1 private-volume backup/restore acceptance against one exact image.

This runner creates only uniquely named Docker volumes and containers and keeps
all synthetic databases and reports under a new, private report directory.
It verifies the backup/restore command-line contract; it is not an application
health check or a substitute for deploy/rollback maintenance-window checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
BACKUP_CLI = SCRIPT_DIR / "backup.sh"
RESTORE_CLI = SCRIPT_DIR / "restore.sh"
MANIFEST_CLI = SCRIPT_DIR / "release_manifest.py"
SNAPSHOT_PY = SCRIPT_DIR / "sqlite_snapshot.py"

OWNER_LABEL = "org.newshub.volume-acceptance.owner"
IMAGE_LABEL = "org.opencontainers.image.revision"
PRODUCTION_USER = "10001:10001"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
VOLUME_PREFIX = "nhpub-volume-"
ROOT_CHOWN_CODE = "import os; os.chown('/fixture',10001,10001)"

CHECK_NAMES = (
    "image_revision_and_uid",
    "release_manifest",
    "fixture_and_volume_permissions",
    "backup_a_private_and_complete",
    "replace_restore_uses_latest_prior",
    "stale_prior_rejected_unchanged",
    "wrong_database_prior_rejected_unchanged",
    "fresh_volume_restore_uid_and_integrity",
    "busy_volume_backup_rejected_unchanged",
    "busy_volume_restore_rejected_unchanged",
    "tampered_snapshot_rejected_unchanged",
    "cleanup",
)


class AcceptanceError(RuntimeError):
    """A contract assertion or a command required by the acceptance failed."""


@dataclass(frozen=True)
class Options:
    image: str
    sha: str
    report_dir: Path


def validate_options(image: str, sha: str, report_dir: str | Path) -> Options:
    """Validate immutable inputs before creating a report directory or Docker resource."""
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
        raise AcceptanceError("--image must be a safe immutable image reference")
    if any(char in image for char in "\n\r\t") or image.endswith(":latest"):
        raise AcceptanceError("--image must not be a mutable latest reference")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise AcceptanceError("--sha must be exactly 40 lowercase hexadecimal characters")
    if "@" in image:
        if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", image):
            raise AcceptanceError("--image digest must be an exact sha256 digest")
    else:
        tag = image.rsplit(":", 1)[-1]
        if not re.search(rf"(?:^|[-_.]){re.escape(sha)}$", tag):
            raise AcceptanceError("--image tag must end with the exact requested SHA")

    path = Path(report_dir)
    if not path.is_absolute():
        raise AcceptanceError("--report-dir must be an absolute path")
    if path.name in {"", ".", ".."}:
        raise AcceptanceError("--report-dir must name a new child directory")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError:
        raise AcceptanceError("--report-dir parent must already exist") from None
    if not parent.is_dir() or path.parent != parent:
        raise AcceptanceError("--report-dir parent must be a real directory without symlinks")
    if path.exists() or path.is_symlink():
        raise AcceptanceError("--report-dir must not already exist")
    return Options(image=image, sha=sha, report_dir=path)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _atomic_private_json(path: Path, value: Any, *, create_only: bool = False) -> None:
    """Write JSON with mode 0600 without following a pre-existing symlink."""
    data = _json_bytes(value)
    if create_only:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_private_jsonl(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def _option_value(args: Sequence[str], option: str) -> str | None:
    values: list[str] = []
    for index, item in enumerate(args):
        if item == option and index + 1 < len(args):
            values.append(args[index + 1])
        elif item.startswith(option + "="):
            values.append(item.partition("=")[2])
    if len(values) > 1 and len(set(values)) != 1:
        raise AcceptanceError(f"conflicting Docker {option} options are forbidden")
    return values[-1] if values else None


DOCKER_RUN_VALUE_OPTIONS = {
    "--pull", "--network", "--user", "--entrypoint", "--mount", "--env",
    "-e", "--name", "--label", "--workdir", "-w", "--hostname",
}
DOCKER_RUN_SHORT_VALUE_OPTIONS = {"-e", "-w"}


def _docker_option_values_before_image(
    args: Sequence[str], image_index: int, option: str,
) -> list[str]:
    """Read every occurrence of one Docker option without inspecting image argv."""
    values: list[str] = []
    index = 1
    while index < image_index:
        item = args[index]
        if item == option:
            if index + 1 >= image_index or args[index + 1].startswith("-"):
                raise AcceptanceError(f"Docker {option} option is missing its value")
            values.append(args[index + 1])
            index += 2
            continue
        if item.startswith(option + "="):
            value = item.partition("=")[2]
            if not value:
                raise AcceptanceError(f"Docker {option} option is missing its value")
            values.append(value)
            index += 1
            continue
        if item in DOCKER_RUN_VALUE_OPTIONS:
            if index + 1 >= image_index:
                raise AcceptanceError(f"Docker {item} option is missing its value")
            index += 2
            continue
        if any(
            item.startswith(value_option + "=")
            for value_option in DOCKER_RUN_VALUE_OPTIONS
            if value_option.startswith("--")
        ):
            index += 1
            continue
        if item in DOCKER_RUN_SHORT_VALUE_OPTIONS:
            if index + 1 >= image_index:
                raise AcceptanceError(f"Docker {item} option is missing its value")
            index += 2
            continue
        index += 1
    return values


def _one_option_value(values: Sequence[str], option: str) -> str | None:
    if len(set(values)) > 1:
        raise AcceptanceError(f"conflicting Docker {option} options are forbidden")
    return values[-1] if values else None


def _options_without_network_and_pull(args: Sequence[str], image_index: int) -> list[str]:
    """Keep Docker options in order while removing normalized network/pull options."""
    retained = [args[0]]
    index = 1
    while index < image_index:
        item = args[index]
        if item in {"--network", "--pull"}:
            index += 2
            continue
        if item.startswith("--network=") or item.startswith("--pull="):
            index += 1
            continue
        if item in DOCKER_RUN_VALUE_OPTIONS or item in DOCKER_RUN_SHORT_VALUE_OPTIONS:
            retained.extend(args[index:min(index + 2, image_index)])
            index += 2
            continue
        if any(
            item.startswith(value_option + "=")
            for value_option in DOCKER_RUN_VALUE_OPTIONS
            if value_option.startswith("--")
        ):
            retained.append(item)
            index += 1
            continue
        retained.append(item)
        index += 1
    return retained


def _docker_mounts(args: Sequence[str]) -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    index = 0
    while index < len(args):
        item = args[index]
        value: str | None = None
        if item == "--mount" and index + 1 < len(args):
            value = args[index + 1]
            index += 1
        elif item.startswith("--mount="):
            value = item.partition("=")[2]
        if value is not None:
            parts: dict[str, str] = {}
            for segment in value.split(","):
                if "=" in segment:
                    key, val = segment.split("=", 1)
                    parts[key] = val
                else:
                    parts[segment] = ""
            mounts.append(parts)
        index += 1
    return mounts


def _image_index(args: Sequence[str]) -> int:
    """Find the image operand in a run/create command, rejecting unsupported syntax."""
    index = 1
    while index < len(args):
        item = args[index]
        if item == "--":
            raise AcceptanceError("Docker run/create must use an explicit image operand")
        if item in DOCKER_RUN_VALUE_OPTIONS:
            index += 2
            continue
        if any(
            item.startswith(option + "=")
            for option in DOCKER_RUN_VALUE_OPTIONS
            if option.startswith("--")
        ):
            index += 1
            continue
        if item.startswith("-"):
            if item in {"--rm", "-i", "-t", "-d", "--init", "--read-only"}:
                index += 1
                continue
            raise AcceptanceError("unsupported Docker run/create option is forbidden")
        return index
    raise AcceptanceError("Docker run/create is missing its image")


def _exec_container_operand(args: Sequence[str]) -> str:
    """Parse only the supported Docker exec user options before its container operand."""
    index = 1
    requested_user: str | None = None
    while index < len(args):
        item = args[index]
        if item in {"--user", "-u"}:
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                raise AcceptanceError("Docker exec user option is missing its value")
            if requested_user is not None:
                raise AcceptanceError("Docker exec user option may be specified only once")
            requested_user = args[index + 1]
            index += 2
            continue
        if item.startswith("--user=") or item.startswith("-u="):
            if requested_user is not None:
                raise AcceptanceError("Docker exec user option may be specified only once")
            requested_user = item.split("=", 1)[1]
            index += 1
            continue
        if item.startswith("-"):
            raise AcceptanceError("unsupported Docker exec option is forbidden")
        break

    if requested_user is not None and requested_user not in {"0:0", PRODUCTION_USER}:
        raise AcceptanceError("Docker exec user must be 0:0 or 10001:10001")
    if index >= len(args):
        raise AcceptanceError("Docker exec is missing its container operand")
    if index + 1 >= len(args):
        raise AcceptanceError("Docker exec is missing its command")
    return args[index]


def secure_docker_argv(
    args: Sequence[str],
    *,
    run_prefix: str,
    owner_token: str,
    image: str,
    snapshot_script: Path,
    ledger_entries: Sequence[dict[str, Any]] = (),
) -> list[str]:
    """Apply the runner's Docker resource/network/mount policy to one CLI call."""
    original = list(args)
    if not original:
        raise AcceptanceError("empty Docker command is forbidden")
    command = original[0]
    owned_names = {entry.get("name") for entry in ledger_entries if entry.get("kind") == "container"}
    owned_ids = {entry.get("id") for entry in ledger_entries if entry.get("kind") == "container"}
    owned_volumes = {entry.get("name") for entry in ledger_entries if entry.get("kind") == "volume"}

    if command in {"run", "create"}:
        image_index = _image_index(original)
        if original[image_index] != image:
            raise AcceptanceError("Docker resource image differs from the requested image")
        docker_options = original[1:image_index]
        if any(
            item in {"-p", "-P", "--publish", "--publish-all", "--privileged", "--volumes-from", "--device", "--tmpfs", "--net", "--detach", "-d"}
            or item.startswith(("--publish=", "--publish-all=", "--volumes-from=", "--device=", "--net="))
            or (item.startswith("-p") and item != "--pull")
            for item in docker_options
        ):
            raise AcceptanceError("published ports, privileged mode, and external mounts are forbidden")
        if any(item == "--volume" or item.startswith("--volume=") for item in docker_options):
            raise AcceptanceError("short-form or host path mounts are forbidden")
        if "--pid" in docker_options or "--ipc" in docker_options or "--cgroupns" in docker_options:
            raise AcceptanceError("host process and IPC namespaces are forbidden")
        networks = _docker_option_values_before_image(original, image_index, "--network")
        pulls = _docker_option_values_before_image(original, image_index, "--pull")
        if any(value != "none" for value in networks) or any(value != "never" for value in pulls):
            raise AcceptanceError("Docker resources must use network none and pull never")
        user = _one_option_value(
            _docker_option_values_before_image(original, image_index, "--user"), "--user",
        )
        if user not in (None, PRODUCTION_USER, "0:0"):
            raise AcceptanceError("Docker resource user is outside the UID 10001 contract")
        mounts = _docker_mounts(docker_options)
        for mount in mounts:
            kind = mount.get("type")
            if kind == "volume":
                if mount.get("source") not in owned_volumes:
                    raise AcceptanceError("Docker resource requested a volume not created by this run")
            elif kind == "bind":
                if not (
                    Path(mount.get("source", "")).resolve(strict=False) == snapshot_script
                    and mount.get("target") == "/tmp/sqlite_snapshot.py"
                    and "readonly" in mount
                ):
                    raise AcceptanceError("Docker bind mounts are restricted to the read-only snapshot helper")
            else:
                raise AcceptanceError("Docker run/create mount type is unsupported")
        for item in docker_options:
            if item == "-v" or item.startswith("-v"):
                raise AcceptanceError("short-form mounts are forbidden")
        if user == "0:0":
            code = None
            command_args = original[image_index + 1:]
            for index, item in enumerate(command_args[:-1]):
                if item == "-c":
                    code = command_args[index + 1]
                    break
            if not (
                command == "run"
                and code == ROOT_CHOWN_CODE
                and len(mounts) == 1
                and mounts[0].get("type") == "volume"
                and mounts[0].get("target") == "/fixture"
            ):
                raise AcceptanceError("root may only chown this run's empty synthetic fixture volume")
        requested_name = _one_option_value(
            _docker_option_values_before_image(original, image_index, "--name"), "--name",
        )
        if requested_name is not None:
            raise AcceptanceError("container names are allocated only by the acceptance runner")
        if any(
            item.startswith(f"--label={OWNER_LABEL}=")
            or (item == "--label" and index + 1 < len(docker_options) and docker_options[index + 1].startswith(OWNER_LABEL + "="))
            for index, item in enumerate(docker_options)
        ):
            raise AcceptanceError("reserved ownership labels are allocated only by the runner")
        name = f"{run_prefix}-c{len(owned_names) + 1:03d}-{secrets.token_hex(3)}"
        rewritten = [command, "--pull=never", "--network=none", "--name", name,
                     "--label", f"{OWNER_LABEL}={owner_token}"]
        rewritten.extend(_options_without_network_and_pull(original, image_index)[1:])
        rewritten.extend(original[image_index:])
        return rewritten

    if command == "volume" and len(original) >= 2 and original[1] == "create":
        names: list[str] = []
        index = 2
        while index < len(original):
            item = original[index]
            if item in {"--label", "-l"}:
                index += 2
                continue
            if item.startswith("--label="):
                index += 1
                continue
            if item.startswith("-"):
                raise AcceptanceError("custom Docker volume drivers/options are forbidden")
            names.append(item)
            index += 1
        if len(names) != 1 or not names[0].startswith(run_prefix + "-"):
            raise AcceptanceError("only a new runner-prefixed named volume may be created")
        if names[0] in owned_volumes:
            raise AcceptanceError("Docker volume name is already in this run's ledger")
        if any(item.startswith(f"--label={OWNER_LABEL}=") for item in original):
            raise AcceptanceError("reserved ownership labels are allocated only by the runner")
        return [*original, "--label", f"{OWNER_LABEL}={owner_token}"]

    if command == "image" and len(original) >= 2 and original[1] == "inspect":
        if original[-1] != image:
            raise AcceptanceError("only the requested image may be inspected")
        return original

    if command == "ps":
        filter_value = _option_value(original, "--filter")
        if filter_value is None or not filter_value.startswith("volume="):
            raise AcceptanceError("Docker process listing must be limited to an owned volume")
        if filter_value.partition("=")[2] not in owned_volumes:
            raise AcceptanceError("Docker process listing requested an unowned volume")
        return original

    if command == "exec":
        container = _exec_container_operand(original)
        if container not in owned_names and container not in owned_ids:
            raise AcceptanceError("Docker command targets a container not created by this run")
        return original

    if command in {"start", "stop", "cp", "rm"}:
        identifiers: list[str] = []
        if command == "cp":
            for item in original[1:]:
                if ":" in item and not item.startswith("/"):
                    identifiers.append(item.partition(":")[0])
        else:
            identifiers = [item for item in original[1:] if not item.startswith("-")]
        if not identifiers or any(item not in owned_names and item not in owned_ids for item in identifiers):
            raise AcceptanceError("Docker command targets a container not created by this run")
        return original

    if command == "container" and len(original) >= 2 and original[1] == "inspect":
        target = original[-1]
        if target not in owned_names and target not in owned_ids:
            raise AcceptanceError("Docker inspect targets a container not created by this run")
        return original

    if command == "volume" and len(original) >= 2 and original[1] in {"inspect", "rm"}:
        targets: list[str] = []
        index = 2
        takes_value = {"--format", "-f"}
        while index < len(original):
            item = original[index]
            if item in takes_value:
                index += 2
                continue
            if any(item.startswith(option + "=") for option in takes_value):
                index += 1
                continue
            if not item.startswith("-"):
                targets.append(item)
            index += 1
        if not targets or any(item not in owned_volumes for item in targets):
            raise AcceptanceError("Docker volume command targets a volume not created by this run")
        return original

    raise AcceptanceError("Docker command is outside the volume acceptance allowlist")


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            raise AcceptanceError("private resource ledger is invalid") from None
        if isinstance(value, dict):
            kind, name = value.get("kind"), value.get("name")
            if not isinstance(kind, str) or not isinstance(name, str):
                raise AcceptanceError("private resource ledger entry is incomplete")
            key = (kind, name)
            if key in positions:
                entries[positions[key]].update(value)
            else:
                positions[key] = len(entries)
                entries.append(value)
    return entries


def docker_proxy_main(argv: Sequence[str]) -> int:
    """Internal executable reached only through the report-dir Docker shim."""
    real_docker = os.environ.get("NHVOL_REAL_DOCKER", "")
    prefix = os.environ.get("NHVOL_PREFIX", "")
    token = os.environ.get("NHVOL_OWNER_TOKEN", "")
    image = os.environ.get("NHVOL_IMAGE", "")
    snapshot = Path(os.environ.get("NHVOL_SNAPSHOT_SCRIPT", "/nonexistent"))
    ledger = Path(os.environ.get("NHVOL_LEDGER", "/nonexistent"))
    command_log = Path(os.environ.get("NHVOL_COMMAND_LOG", "/nonexistent"))
    if not real_docker or not prefix.startswith(VOLUME_PREFIX) or not token or not image:
        print("volume-acceptance docker proxy configuration is invalid", file=sys.stderr)
        return 125
    try:
        entries = _read_ledger(ledger)
        rewritten = secure_docker_argv(
            argv,
            run_prefix=prefix,
            owner_token=token,
            image=image,
            snapshot_script=snapshot,
            ledger_entries=entries,
        )
    except AcceptanceError as exc:
        print(f"volume-acceptance docker policy: {exc}", file=sys.stderr)
        return 125

    resource_intent: dict[str, Any] | None = None
    if rewritten[0] in {"create", "run"}:
        resource_intent = {
            "kind": "container",
            "name": _option_value(rewritten, "--name"),
            "id": "",
            "owner_label": OWNER_LABEL,
            "owner_token": token,
            "auto_remove": "--rm" in rewritten,
            "state": "intent",
        }
    elif rewritten[:2] == ["volume", "create"]:
        names: list[str] = []
        index = 2
        while index < len(rewritten):
            item = rewritten[index]
            if item in {"--label", "-l"}:
                index += 2
                continue
            if item.startswith("--label="):
                index += 1
                continue
            if not item.startswith("-"):
                names.append(item)
            index += 1
        if len(names) != 1:
            print("volume-acceptance Docker volume intent is ambiguous", file=sys.stderr)
            return 125
        resource_intent = {
            "kind": "volume", "name": names[0], "owner_label": OWNER_LABEL,
            "owner_token": token, "state": "intent",
        }

    if resource_intent is not None:
        # Persist the unique owned name and label before the daemon can create it.
        _append_private_jsonl(ledger, resource_intent)

    started = time.monotonic()
    try:
        timeout_seconds = float(os.environ.get("NHVOL_DOCKER_TIMEOUT_SECONDS", "150"))
        result = subprocess.run(
            [real_docker, *rewritten], capture_output=True, check=False, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        _append_private_jsonl(command_log, {"operation": rewritten[0], "exit_code": 124, "error": "TimeoutExpired", "elapsed_ms": elapsed_ms})
        if resource_intent is not None:
            _append_private_jsonl(ledger, {**resource_intent, "state": "timeout"})
        print("volume-acceptance Docker command timed out", file=sys.stderr)
        return 124
    except OSError:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        _append_private_jsonl(command_log, {"operation": rewritten[0], "exit_code": 127, "error": "OSError", "elapsed_ms": elapsed_ms})
        if resource_intent is not None:
            _append_private_jsonl(ledger, {**resource_intent, "state": "unresolved"})
        print("volume-acceptance could not execute Docker CLI", file=sys.stderr)
        return 127
    elapsed_ms = round((time.monotonic() - started) * 1000)
    operation = rewritten[0] if rewritten[0] != "volume" and rewritten[0] != "image" else " ".join(rewritten[:2])
    _append_private_jsonl(command_log, {"operation": operation, "exit_code": result.returncode, "elapsed_ms": elapsed_ms})
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    if resource_intent is not None:
        update = {**resource_intent, "state": "created" if result.returncode == 0 else "result_nonzero"}
        if result.returncode == 0 and resource_intent["kind"] == "container" and rewritten[0] == "create":
            candidate = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
            if candidate and re.fullmatch(r"[0-9a-f]{12,64}", candidate[-1]):
                update["id"] = candidate[-1]
        if result.returncode == 0 and resource_intent["kind"] == "volume":
            candidate = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
            if candidate and candidate[-1] != resource_intent["name"]:
                update["state"] = "uncertain_result"
        _append_private_jsonl(ledger, update)
    return result.returncode


class AcceptanceRunner:
    def __init__(self, options: Options):
        self.options = options
        self.report_dir = options.report_dir
        self.token = secrets.token_hex(12)
        self.prefix = f"{VOLUME_PREFIX}{self.token}"
        self.real_docker = shutil.which("docker")
        self.bin_dir = self.report_dir / ".private-bin"
        self.ledger_path = self.report_dir / "resources.jsonl"
        self.command_log_path = self.report_dir / "commands.jsonl"
        self.report_path = self.report_dir / "report.json"
        self.manifest_path = self.report_dir / "release-manifest.json"
        self.snapshot_dir = self.report_dir / "snapshots"
        self.source_volume = f"{self.prefix}-source"
        self.target_volume = f"{self.prefix}-target"
        self.wrong_volume = f"{self.prefix}-wrong"
        self.source_a = self.snapshot_dir / "source-a.sqlite3"
        self.source_ab = self.snapshot_dir / "source-ab.sqlite3"
        self.source_ab_latest = self.snapshot_dir / "source-ab-latest.sqlite3"
        self.wrong_snapshot = self.snapshot_dir / "wrong.sqlite3"
        self.target_prior = self.snapshot_dir / "target-prior.sqlite3"
        self.busy_backup = self.snapshot_dir / "busy.sqlite3"
        self.tampered = self.snapshot_dir / "tampered.sqlite3"
        self.report: dict[str, Any] = {
            "task_id": "G1-VOLUME-RUNTIME",
            "requested_image": options.image,
            "requested_sha": options.sha,
            "overall": "FAIL",
            "checks": {name: {"status": "NOT_RUN"} for name in CHECK_NAMES},
            "scope": (
                "Checks the formal snapshot/backup/restore CLI and UID 10001 volume access only. "
                "Does not verify application health, deploy/rollback maintenance-window behavior, or browser behavior."
            ),
            "resources": {"prefix": self.prefix, "created_volumes": [], "created_containers": []},
        }
        self.child_env: dict[str, str] = {}
        self.workspace_created = False
        self.workspace_identity: tuple[int, int] | None = None
        self.busy_before: list[str] | None = None

    def _prepare_workspace(self) -> None:
        self.report_dir.mkdir(mode=0o700)
        workspace_stat = self.report_dir.lstat()
        if not stat.S_ISDIR(workspace_stat.st_mode):
            raise AcceptanceError("report workspace is not a real directory")
        self.workspace_identity = (workspace_stat.st_dev, workspace_stat.st_ino)
        self.workspace_created = True
        os.chmod(self.report_dir, 0o700)
        self.bin_dir.mkdir(mode=0o700)
        self.snapshot_dir.mkdir(mode=0o700)
        if self.real_docker is None:
            raise AcceptanceError("Docker CLI is unavailable; no runtime checks were run")
        shim = self.bin_dir / "docker"
        shim.write_text(
            "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(Path(__file__).resolve())) +
            " --_docker-proxy \"$@\"\n",
            encoding="utf-8",
        )
        os.chmod(shim, 0o700)
        self.child_env = os.environ.copy()
        self.child_env.update({
            "PATH": os.fspath(self.bin_dir) + os.pathsep + os.fspath(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            "NHVOL_REAL_DOCKER": self.real_docker,
            "NHVOL_PREFIX": self.prefix,
            "NHVOL_OWNER_TOKEN": self.token,
            "NHVOL_IMAGE": self.options.image,
            "NHVOL_SNAPSHOT_SCRIPT": os.fspath(SNAPSHOT_PY),
            "NHVOL_LEDGER": os.fspath(self.ledger_path),
            "NHVOL_COMMAND_LOG": os.fspath(self.command_log_path),
        })
        os.umask(0o077)

    def _command(self, label: str, argv: Sequence[str], *, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        command_env = self.child_env.copy()
        if command_env:
            command_env["NHVOL_DOCKER_TIMEOUT_SECONDS"] = str(max(1.0, min(150.0, timeout - 5.0)))
        try:
            result = subprocess.run(
                list(argv), text=True, capture_output=True, check=False,
                timeout=timeout, env=command_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _append_private_jsonl(self.command_log_path, {
                "operation": label, "exit_code": None,
                "error": type(exc).__name__,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            })
            raise AcceptanceError(f"{label} could not complete ({type(exc).__name__})") from None
        _append_private_jsonl(self.command_log_path, {
            "operation": label, "exit_code": result.returncode,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        })
        return result

    def _expect_zero(self, label: str, argv: Sequence[str], *, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
        result = self._command(label, argv, timeout=timeout)
        if result.returncode != 0:
            raise AcceptanceError(f"{label} returned exit code {result.returncode}")
        return result

    def _cli(self, label: str, script: Path, args: Sequence[str], *, expect_success: bool, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
        result = self._command(label, [os.fspath(script), *args], timeout=timeout)
        if (result.returncode == 0) != expect_success:
            expected = "succeed" if expect_success else "reject"
            raise AcceptanceError(f"{label} did not {expected} (exit code {result.returncode})")
        return result

    def _case(self, name: str, action: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
        try:
            details = action() or {}
        except Exception as exc:
            self.report["checks"][name] = {"status": "FAIL", "detail": str(exc)}
            raise
        self.report["checks"][name] = {"status": "PASS", **details}
        self._save_report()
        return details

    def _save_report(self) -> None:
        if not self._owns_workspace():
            raise AcceptanceError("refused to write outside this run's private report workspace")
        _atomic_private_json(self.report_path, self.report)

    def _owns_workspace(self) -> bool:
        if not self.workspace_created or self.workspace_identity is None:
            return False
        try:
            current = self.report_dir.lstat()
        except OSError:
            return False
        return (
            stat.S_ISDIR(current.st_mode)
            and (current.st_dev, current.st_ino) == self.workspace_identity
        )

    def _run_helper(self, label: str, volume: str, code: str, *, user: str = PRODUCTION_USER, target: str = "/fixture", timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
        return self._command(label, [
            "docker", "run", "--rm", "--pull=never", "--network", "none", "--user", user,
            "--entrypoint", "python", "--mount", f"type=volume,source={volume},target={target}",
            self.options.image, "-c", code,
        ], timeout=timeout)

    def _ensure_volume_writable(self, volume: str) -> None:
        probe_code = (
            "import os,sys\n"
            "try:\n"
            " f=open('/fixture/.uid10001-probe','x'); f.close(); os.unlink('/fixture/.uid10001-probe')\n"
            " print('WRITE_OK')\n"
            "except PermissionError:\n"
            " print('WRITE_DENIED'); sys.exit(73)\n"
        )
        probe = self._run_helper("volume_write_probe_uid10001", volume, probe_code)
        if probe.returncode == 0 and "WRITE_OK" in probe.stdout:
            return
        if probe.returncode != 73 or "WRITE_DENIED" not in probe.stdout:
            raise AcceptanceError("UID 10001 volume write probe failed for a reason other than empty-volume ownership")
        chown = self._run_helper("chown_owned_empty_volume", volume, ROOT_CHOWN_CODE, user="0:0")
        if chown.returncode != 0:
            raise AcceptanceError("root could not chown this run's empty synthetic volume")
        retry = self._run_helper("volume_write_probe_after_chown", volume, probe_code)
        if retry.returncode != 0 or "WRITE_OK" not in retry.stdout:
            raise AcceptanceError("UID 10001 could not write to this run's prepared volume")

    @staticmethod
    def _fixture_code(migrations: list[dict[str, str]], marker: str, *, append: bool = False) -> str:
        payload = json.dumps(migrations, separators=(",", ":"))
        if append:
            return (
                "import sqlite3\n"
                "p='/fixture/db.sqlite3'; c=sqlite3.connect(p)\n"
                "c.execute('INSERT INTO fixture_rows(marker) VALUES (?)', ('B',)); c.commit(); c.close()\n"
            )
        return (
            "import json,sqlite3\n"
            "migrations=json.loads(" + repr(payload) + ")\n"
            "c=sqlite3.connect('/fixture/db.sqlite3')\n"
            "c.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, app varchar(255), name varchar(255), applied datetime)')\n"
            "c.executemany('INSERT INTO django_migrations(app,name,applied) VALUES (?,?,CURRENT_TIMESTAMP)', [(m['app'],m['name']) for m in migrations])\n"
            "c.execute('CREATE TABLE fixture_rows (id INTEGER PRIMARY KEY AUTOINCREMENT, marker TEXT NOT NULL)')\n"
            "c.execute('INSERT INTO fixture_rows(marker) VALUES (?)', (" + repr(marker) + ",))\n"
            "c.commit(); c.close()\n"
        )

    def _read_volume(self, volume: str) -> list[str]:
        code = (
            "import json,sqlite3\n"
            "c=sqlite3.connect('/fixture/db.sqlite3')\n"
            "print(json.dumps([r[0] for r in c.execute('SELECT marker FROM fixture_rows ORDER BY id')]))\n"
            "c.close()\n"
        )
        result = self._expect_zero("read_synthetic_volume_rows", [
            "docker", "run", "--rm", "--pull=never", "--network", "none", "--user", PRODUCTION_USER,
            "--entrypoint", "python", "--mount", f"type=volume,source={volume},target=/fixture,readonly",
            self.options.image, "-c", code,
        ])
        try:
            rows = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError, TypeError):
            raise AcceptanceError("synthetic volume row output was invalid") from None
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
            raise AcceptanceError("synthetic volume row output was invalid")
        return rows

    @staticmethod
    def _uid_integrity_code() -> str:
        return (
            "import json,os,sqlite3\n"
            "p='/fixture/db.sqlite3'; c=sqlite3.connect(p)\n"
            "integrity=c.execute('PRAGMA integrity_check').fetchone()[0]\n"
            "rows=[r[0] for r in c.execute('SELECT marker FROM fixture_rows ORDER BY id')]\n"
            "c.execute('INSERT INTO fixture_rows(marker) VALUES (?)', ('UID10001_WRITE_CHECK',)); c.commit()\n"
            "c.execute(\"DELETE FROM fixture_rows WHERE marker='UID10001_WRITE_CHECK'\"); c.commit()\n"
            "print(json.dumps({'integrity':integrity,'rows':rows,'uid':os.geteuid()})); c.close()\n"
        )

    def _read_snapshot(self, path: Path) -> tuple[list[str], list[dict[str, str]]]:
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                rows = [str(row[0]) for row in connection.execute("SELECT marker FROM fixture_rows ORDER BY id")]
                migrations = [
                    {"app": str(app), "name": str(name)}
                    for app, name in connection.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
                ]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise AcceptanceError(f"snapshot content could not be read ({type(exc).__name__})") from None
        return rows, migrations

    def _backup(self, label: str, volume: str, output: Path) -> subprocess.CompletedProcess[str]:
        return self._cli(label, BACKUP_CLI, [
            "--execute", "--volume", volume, "--image", self.options.image, "--sha", self.options.sha,
            "--filename", output.name, "--output-dir", os.fspath(output.parent), "--manifest", os.fspath(self.manifest_path),
        ], expect_success=True, timeout=240.0)

    def _restore(self, label: str, snapshot: Path, volume: str, *, replace: bool = False, prior: Path | None = None, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        args = [
            "--execute", "--snapshot", os.fspath(snapshot), "--volume", volume,
            "--image", self.options.image, "--sha", self.options.sha, "--manifest", os.fspath(self.manifest_path),
        ]
        if replace:
            args.extend(["--replace", "--writers-stopped", "--prior-backup", os.fspath(prior)])
        return self._cli(label, RESTORE_CLI, args, expect_success=expect_success, timeout=240.0)

    def _assert_snapshot_private_and_matches(self, snapshot: Path, expected_rows: list[str], expected_migrations: list[dict[str, str]]) -> None:
        sidecar = Path(f"{snapshot}.manifest.json")
        for path in (snapshot, sidecar):
            if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise AcceptanceError("snapshot and sidecar must be regular private mode-0600 files")
        rows, migrations = self._read_snapshot(snapshot)
        if rows != expected_rows or migrations != expected_migrations:
            raise AcceptanceError("snapshot contents do not match the requested fixture and image migration schema")

    def _case_manifest(self) -> dict[str, Any]:
        result = self._expect_zero("release_manifest_describe_exact_image", [
            sys.executable, os.fspath(MANIFEST_CLI), "describe", "--image", self.options.image,
            "--sha", self.options.sha, "--output", os.fspath(self.manifest_path),
        ], timeout=120.0)
        del result
        if stat.S_IMODE(self.manifest_path.stat().st_mode) != 0o600 or self.manifest_path.is_symlink():
            raise AcceptanceError("release manifest must be a regular private mode-0600 file")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("release_sha") != self.options.sha or manifest.get("image") != self.options.image:
            raise AcceptanceError("formal release manifest does not match the requested image and SHA")
        migrations = manifest.get("migrations")
        if not isinstance(migrations, list) or any(not isinstance(item, dict) for item in migrations):
            raise AcceptanceError("formal release manifest migration schema is invalid")
        self._migrations = migrations
        return {"migration_count": len(migrations), "manifest_mode": "0600"}

    def _case_fixture(self) -> dict[str, Any]:
        self._expect_zero("create_source_volume", ["docker", "volume", "create", self.source_volume])
        self._expect_zero("create_target_volume", ["docker", "volume", "create", self.target_volume])
        self._expect_zero("create_wrong_volume", ["docker", "volume", "create", self.wrong_volume])
        self.report["resources"]["created_volumes"] = [self.source_volume, self.target_volume, self.wrong_volume]
        self._ensure_volume_writable(self.source_volume)
        self._ensure_volume_writable(self.target_volume)
        self._ensure_volume_writable(self.wrong_volume)
        init = self._run_helper("create_source_fixture_a_uid10001", self.source_volume, self._fixture_code(self._migrations, "A"))
        if init.returncode != 0:
            raise AcceptanceError("could not create fixture A as UID 10001")
        wrong_init = self._run_helper("create_wrong_database_fixture_uid10001", self.wrong_volume, self._fixture_code(self._migrations, "WRONG"))
        if wrong_init.returncode != 0:
            raise AcceptanceError("could not create the distinct prior-backup fixture as UID 10001")
        if self._read_volume(self.source_volume) != ["A"]:
            raise AcceptanceError("initial source fixture contents differ from A")
        if self._read_volume(self.wrong_volume) != ["WRONG"]:
            raise AcceptanceError("wrong-database fixture contents differ from WRONG")
        return {"fixture_schema": "django_migrations + fixture_rows", "fixture_uid": PRODUCTION_USER}

    def _case_backup_a(self) -> dict[str, Any]:
        self._backup("backup_fixture_a", self.source_volume, self.source_a)
        self._assert_snapshot_private_and_matches(self.source_a, ["A"], self._migrations)
        return {"snapshot": self.source_a.name, "mode": "0600", "rows": ["A"]}

    def _case_replace_restore(self) -> dict[str, Any]:
        add_b = self._run_helper("add_fixture_b_uid10001", self.source_volume, self._fixture_code(self._migrations, "", append=True))
        if add_b.returncode != 0 or self._read_volume(self.source_volume) != ["A", "B"]:
            raise AcceptanceError("could not prepare source fixture AB")
        self._backup("backup_latest_ab_prior", self.source_volume, self.source_ab)
        self._assert_snapshot_private_and_matches(self.source_ab, ["A", "B"], self._migrations)
        self._restore("restore_a_over_ab_with_latest_prior", self.source_a, self.source_volume, replace=True, prior=self.source_ab)
        if self._read_volume(self.source_volume) != ["A"]:
            raise AcceptanceError("replace restore did not produce exact fixture A")
        add_b_again = self._run_helper("readd_fixture_b_uid10001", self.source_volume, self._fixture_code(self._migrations, "", append=True))
        if add_b_again.returncode != 0 or self._read_volume(self.source_volume) != ["A", "B"]:
            raise AcceptanceError("could not prepare AB target for stale-prior checks")
        self._backup("backup_latest_ab_for_negative_checks", self.source_volume, self.source_ab_latest)
        self._assert_snapshot_private_and_matches(self.source_ab_latest, ["A", "B"], self._migrations)
        self._backup("backup_wrong_database_prior", self.wrong_volume, self.wrong_snapshot)
        self._assert_snapshot_private_and_matches(self.wrong_snapshot, ["WRONG"], self._migrations)
        return {"restore_rows": ["A"], "latest_prior_rows": ["A", "B"]}

    def _case_stale_prior(self) -> dict[str, Any]:
        before = self._read_volume(self.source_volume)
        if before != ["A", "B"]:
            raise AcceptanceError("stale-prior target precondition is not AB")
        self._restore("restore_with_stale_prior_expected_rejection", self.source_a, self.source_volume, replace=True, prior=self.source_a, expect_success=False)
        if self._read_volume(self.source_volume) != before:
            raise AcceptanceError("stale prior rejection changed the target volume")
        return {"cli_exit_nonzero": True, "target_rows_unchanged": before}

    def _case_wrong_prior(self) -> dict[str, Any]:
        before = self._read_volume(self.source_volume)
        if before != ["A", "B"]:
            raise AcceptanceError("wrong-prior target precondition is not AB")
        self._restore("restore_with_wrong_database_prior_expected_rejection", self.source_a, self.source_volume, replace=True, prior=self.wrong_snapshot, expect_success=False)
        if self._read_volume(self.source_volume) != before:
            raise AcceptanceError("wrong-database prior rejection changed the target volume")
        return {"cli_exit_nonzero": True, "target_rows_unchanged": before}

    def _case_fresh_restore(self) -> dict[str, Any]:
        self._restore("restore_snapshot_a_to_fresh_volume", self.source_a, self.target_volume)
        code = self._uid_integrity_code()
        result = self._expect_zero("verify_restored_volume_uid_and_integrity", [
            "docker", "run", "--rm", "--pull=never", "--network", "none", "--user", PRODUCTION_USER,
            "--entrypoint", "python", "--mount", f"type=volume,source={self.target_volume},target=/fixture",
            self.options.image, "-c", code,
        ])
        try:
            details = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            raise AcceptanceError("restored volume UID/integrity result was invalid") from None
        if details != {"integrity": "ok", "rows": ["A"], "uid": 10001}:
            raise AcceptanceError("restored volume failed integrity, content, or UID 10001 read/write checks")
        return {"integrity_check": "ok", "rows": ["A"], "uid": 10001, "uid_read_write": True}

    def _case_busy_backup(self) -> dict[str, Any]:
        before = self._read_volume(self.source_volume)
        if before != ["A", "B"]:
            raise AcceptanceError("busy-volume target precondition is not AB")
        self.busy_before = before
        sleeper = self._expect_zero("create_busy_volume_container", [
            "docker", "create", "--pull=never", "--network", "none", "--user", PRODUCTION_USER,
            "--entrypoint", "python", "--mount", f"type=volume,source={self.source_volume},target=/fixture",
            self.options.image, "-c", "import time; time.sleep(300)",
        ])
        container_id = sleeper.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            raise AcceptanceError("busy-volume container creation returned an invalid ID")
        self.report["resources"]["created_containers"] = [container_id]
        self._expect_zero("start_busy_volume_container", ["docker", "start", container_id])
        backup_result = self._cli("backup_busy_volume_expected_rejection", BACKUP_CLI, [
            "--execute", "--volume", self.source_volume, "--image", self.options.image,
            "--sha", self.options.sha, "--filename", self.busy_backup.name,
            "--output-dir", os.fspath(self.busy_backup.parent), "--manifest", os.fspath(self.manifest_path),
        ], expect_success=False)
        if backup_result.returncode == 0 or self.busy_backup.exists() or Path(f"{self.busy_backup}.manifest.json").exists():
            raise AcceptanceError("backup did not reject a volume with a running writer or created artifacts")
        if self._read_volume(self.source_volume) != before:
            raise AcceptanceError("busy-volume backup rejection changed the database rows")
        return {"cli_exit_nonzero": True, "target_rows_unchanged": before}

    def _case_busy_restore(self) -> dict[str, Any]:
        before = self.busy_before
        if before != ["A", "B"]:
            raise AcceptanceError("busy-volume restore precondition is not AB with a runner-owned live container")
        self._restore("restore_busy_volume_expected_rejection", self.source_a, self.source_volume, replace=True, prior=self.source_ab_latest, expect_success=False)
        if self._read_volume(self.source_volume) != before:
            raise AcceptanceError("busy-volume restore rejection changed the database rows")
        return {"cli_exit_nonzero": True, "target_rows_unchanged": before}

    def _case_tampered(self) -> dict[str, Any]:
        before = self._read_volume(self.target_volume)
        if before != ["A"]:
            raise AcceptanceError("tampered-snapshot target precondition is not A")
        target_prior = self.snapshot_dir / self.target_prior.name
        self._backup("backup_target_before_tamper_test", self.target_volume, target_prior)
        with self.source_a.open("rb") as source, self.tampered.open("xb") as target:
            data = source.read_bytes()
            if len(data) < 200:
                raise AcceptanceError("synthetic snapshot is unexpectedly small")
            target.write(data[:-1] + bytes([data[-1] ^ 1]))
        os.chmod(self.tampered, 0o600)
        sidecar = Path(f"{self.source_a}.manifest.json")
        shutil.copyfile(sidecar, Path(f"{self.tampered}.manifest.json"))
        os.chmod(Path(f"{self.tampered}.manifest.json"), 0o600)
        self._restore("restore_tampered_snapshot_expected_rejection", self.tampered, self.target_volume, replace=True, prior=target_prior, expect_success=False)
        if self._read_volume(self.target_volume) != before:
            raise AcceptanceError("tampered snapshot rejection changed the target volume")
        return {"cli_exit_nonzero": True, "target_rows_unchanged": before}

    def _resource_details(self) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        entries = _read_ledger(self.ledger_path)
        containers = [entry for entry in entries if entry.get("kind") == "container"]
        volumes = [str(entry.get("name")) for entry in entries if entry.get("kind") == "volume"]
        return containers, volumes, entries

    @staticmethod
    def _explicit_not_found(result: subprocess.CompletedProcess[str], kind: str, name: str) -> bool:
        output = (result.stdout + "\n" + result.stderr).lower()
        target = name.lower()
        if kind == "container":
            return target in output and any(marker in output for marker in ("no such object:", "no such container:"))
        if kind == "volume":
            return target in output and "no such volume" in output
        return False

    def _cleanup(self) -> None:
        errors: list[str] = []
        containers, volumes, ledger_entries = self._resource_details()
        cleaned_containers: list[str] = []
        absent_containers: list[str] = []
        for entry in reversed(containers):
            name = entry.get("name")
            if not isinstance(name, str) or not name.startswith(self.prefix + "-"):
                errors.append("ledger contained an invalid container name")
                continue
            if entry.get("owner_label") != OWNER_LABEL or entry.get("owner_token") != self.token:
                errors.append("container ledger ownership does not match this run")
                continue
            label = self._command("verify_owned_container_label", [
                "docker", "container", "inspect", "--format", f"{{{{ index .Config.Labels \"{OWNER_LABEL}\" }}}}", name,
            ])
            if label.returncode != 0:
                if self._explicit_not_found(label, "container", name):
                    absent_containers.append(name)
                    continue
                errors.append("container inspection failed without explicit Docker not-found evidence")
                continue
            if label.stdout.strip() != self.token:
                errors.append("refused to remove container without this run's ownership label")
                continue
            inspect_id = self._command("resolve_owned_container_id", [
                "docker", "container", "inspect", "--format", "{{.Id}}", name,
            ])
            container_id = inspect_id.stdout.strip()
            if inspect_id.returncode != 0 or not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
                errors.append("could not resolve owned container ID for cleanup")
                continue
            _append_private_jsonl(
                self.ledger_path,
                {**entry, "id": container_id, "state": "verified_for_cleanup"},
            )
            remove = self._command("remove_owned_container_id", ["docker", "rm", "-f", container_id])
            if remove.returncode != 0:
                errors.append("could not remove owned container ID")
            else:
                cleaned_containers.append(container_id)

        cleaned_volumes: list[str] = []
        absent_volumes: list[str] = []
        for name in reversed(volumes):
            if not name.startswith(self.prefix + "-"):
                errors.append("ledger contained an invalid volume name")
                continue
            volume_entry = next((entry for entry in ledger_entries if entry.get("kind") == "volume" and entry.get("name") == name), {})
            if volume_entry.get("owner_label") != OWNER_LABEL or volume_entry.get("owner_token") != self.token:
                errors.append("volume ledger ownership does not match this run")
                continue
            label = self._command("verify_owned_volume_label", [
                "docker", "volume", "inspect", "--format", f"{{{{ index .Labels \"{OWNER_LABEL}\" }}}}", name,
            ])
            if label.returncode != 0:
                if self._explicit_not_found(label, "volume", name):
                    absent_volumes.append(name)
                    continue
                errors.append("volume inspection failed without explicit Docker not-found evidence")
                continue
            if label.stdout.strip() != self.token:
                errors.append("refused to remove volume without this run's ownership label")
                continue
            remove = self._command("remove_owned_volume", ["docker", "volume", "rm", name])
            if remove.returncode != 0:
                errors.append("could not remove an owned volume")
            else:
                cleaned_volumes.append(name)

        self.report["resources"]["created_containers"] = [entry.get("id") for entry in containers if entry.get("id")]
        self.report["resources"]["created_volumes"] = volumes
        self.report["resources"]["cleaned_container_ids"] = cleaned_containers
        self.report["resources"]["cleaned_volumes"] = cleaned_volumes
        self.report["resources"]["absent_containers"] = absent_containers
        self.report["resources"]["absent_volumes"] = absent_volumes
        self.report["resources"]["ledger"] = [
            {key: entry.get(key) for key in ("kind", "name", "id", "owner_label", "owner_token", "state", "auto_remove") if key in entry}
            for entry in ledger_entries
        ]
        if errors:
            raise AcceptanceError("cleanup did not fully verify/remove this run's resources: " + "; ".join(errors))

    def run(self) -> int:
        try:
            self._prepare_workspace()
            self._save_report()
            # Formal release metadata inspection verifies the exact revision label and Config.User.
            self._case("image_revision_and_uid", self._case_manifest)
            self.report["checks"]["release_manifest"] = {"status": "PASS", "manifest": "formal release_manifest describe"}
            self._save_report()
            self._case("fixture_and_volume_permissions", self._case_fixture)
            self._case("backup_a_private_and_complete", self._case_backup_a)
            self._case("replace_restore_uses_latest_prior", self._case_replace_restore)
            self._case("stale_prior_rejected_unchanged", self._case_stale_prior)
            self._case("wrong_database_prior_rejected_unchanged", self._case_wrong_prior)
            self._case("fresh_volume_restore_uid_and_integrity", self._case_fresh_restore)
            self._case("busy_volume_backup_rejected_unchanged", self._case_busy_backup)
            self._case("busy_volume_restore_rejected_unchanged", self._case_busy_restore)
            self._case("tampered_snapshot_rejected_unchanged", self._case_tampered)
        except Exception as exc:
            self.report["error"] = str(exc)
        finally:
            if not self._owns_workspace():
                error = "report workspace was not created by this run or is no longer owned"
                self.report["checks"]["cleanup"] = {"status": "FAIL", "detail": error}
                if "error" not in self.report:
                    self.report["error"] = error
                self.report["overall"] = "FAIL"
            else:
                try:
                    if self.real_docker and self.child_env:
                        self._cleanup()
                    self.report["checks"]["cleanup"] = {"status": "PASS"}
                except Exception as exc:
                    self.report["checks"]["cleanup"] = {"status": "FAIL", "detail": str(exc)}
                    if "error" not in self.report:
                        self.report["error"] = str(exc)
                if self._owns_workspace():
                    if not self.report_path.exists():
                        # Preflight failures after our directory creation remain visible.
                        self._save_report()
                    statuses = [self.report["checks"][name]["status"] for name in CHECK_NAMES]
                    self.report["overall"] = "PASS" if all(status == "PASS" for status in statuses) else "FAIL"
                    self._save_report()
                else:
                    self.report["overall"] = "FAIL"
        return 0 if self.report["overall"] == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="exact immutable production image reference")
    parser.add_argument("--sha", required=True, help="full 40-character release revision")
    parser.add_argument("--report-dir", required=True, help="absolute path to a new private evidence directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "--_docker-proxy":
        return docker_proxy_main(values[1:])
    parser = _parser()
    args = parser.parse_args(values)
    try:
        options = validate_options(args.image, args.sha, args.report_dir)
    except AcceptanceError as exc:
        parser.error(str(exc))
    return AcceptanceRunner(options).run()


if __name__ == "__main__":
    raise SystemExit(main())
