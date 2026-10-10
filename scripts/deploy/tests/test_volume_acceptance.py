from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.deploy import volume_acceptance as acceptance


SHA = "a" * 40
IMAGE = f"newshub:{SHA}"


def options(tmp_path: Path) -> acceptance.Options:
    return acceptance.validate_options(IMAGE, SHA, tmp_path / "new-report")


def test_validate_options_requires_exact_sha_immutable_image_and_new_absolute_directory(tmp_path):
    valid = acceptance.validate_options(IMAGE, SHA, tmp_path / "evidence")
    assert valid.sha == SHA
    assert valid.report_dir == tmp_path / "evidence"

    for image, sha, report in (
        (f"newshub:{'b' * 40}", SHA, tmp_path / "bad-image"),
        (IMAGE, "A" * 40, tmp_path / "bad-sha"),
        ("newshub:latest", SHA, tmp_path / "latest"),
        (IMAGE, SHA, Path("relative-report")),
    ):
        with pytest.raises(acceptance.AcceptanceError):
            acceptance.validate_options(image, sha, report)

    already_exists = tmp_path / "existing"
    already_exists.mkdir()
    with pytest.raises(acceptance.AcceptanceError, match="must not already exist"):
        acceptance.validate_options(IMAGE, SHA, already_exists)


def test_synthetic_fixture_and_uid_integrity_helpers_are_valid_python(tmp_path):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    compile(runner._fixture_code([], "A"), "<fixture-helper>", "exec")
    compile(runner._fixture_code([], "", append=True), "<append-helper>", "exec")
    compile(runner._uid_integrity_code(), "<uid-integrity-helper>", "exec")


def test_secure_docker_policy_names_resources_and_locks_network_image_and_mounts(tmp_path):
    prefix = "nhpub-volume-0123456789abcdef01234567"
    token = "0123456789abcdef01234567"
    volume = prefix + "-source"
    snapshot_script = Path("/repo/scripts/deploy/sqlite_snapshot.py").resolve()
    ledger = [{"kind": "volume", "name": volume}]

    command = acceptance.secure_docker_argv(
        [
            "create", "--user", "10001:10001", "--mount",
            f"type=volume,source={volume},target=/source,readonly", IMAGE,
            "-c", "import time; time.sleep(1)",
        ],
        run_prefix=prefix,
        owner_token=token,
        image=IMAGE,
        snapshot_script=snapshot_script,
        ledger_entries=ledger,
    )

    assert command[0] == "create"
    assert command[1:3] == ["--pull=never", "--network=none"]
    name = command[command.index("--name") + 1]
    assert name.startswith(prefix + "-")
    assert command[command.index("--label") + 1] == f"{acceptance.OWNER_LABEL}={token}"
    assert command[command.index(IMAGE) + 1:] == ["-c", "import time; time.sleep(1)"]

    readonly_bind = acceptance.secure_docker_argv(
        [
            "create", "--mount",
            f"type=bind,source={snapshot_script},target=/tmp/sqlite_snapshot.py,readonly",
            IMAGE, "-c", "pass",
        ],
        run_prefix=prefix,
        owner_token=token,
        image=IMAGE,
        snapshot_script=snapshot_script,
    )
    assert readonly_bind[0] == "create"


@pytest.mark.parametrize("command", ["run", "create"])
@pytest.mark.parametrize(
    "network_pull_options",
    [
        [],
        ["--network", "none", "--pull", "never"],
        ["--network=none", "--pull=never"],
        ["--network", "none", "--network=none", "--pull=never", "--pull", "never"],
        ["--label", "description=--network=host --pull=always"],
    ],
)
def test_secure_docker_normalizes_pre_image_network_and_pull_options_only(
    command, network_pull_options, tmp_path
):
    prefix = "nhpub-volume-normalize-test"
    tail = [
        IMAGE,
        "python", "-c", "print('--network=host --pull=always')",
        "--network=host", "--pull=always",
    ]
    rewritten = acceptance.secure_docker_argv(
        [command, *network_pull_options, *tail],
        run_prefix=prefix,
        owner_token="normalize-token",
        image=IMAGE,
        snapshot_script=tmp_path / "sqlite_snapshot.py",
    )

    image_index = rewritten.index(IMAGE)
    docker_options = rewritten[1:image_index]
    assert docker_options.count("--pull=never") == 1
    assert docker_options.count("--network=none") == 1
    assert "--pull" not in docker_options
    assert "--network" not in docker_options
    assert rewritten[image_index:] == tail


@pytest.mark.parametrize("command", ["run", "create"])
@pytest.mark.parametrize(
    "network_pull_options",
    [
        ["--network=none", "--network=host"],
        ["--network", "host", "--network=none"],
        ["--network=none", "--network", "none", "--network=host"],
        ["--pull=never", "--pull=always"],
        ["--pull", "always", "--pull=never"],
        ["--network="],
        ["--pull="],
        ["--network"],
        ["--pull"],
    ],
)
def test_secure_docker_rejects_any_unsafe_or_missing_duplicate_network_pull_option(
    command, network_pull_options, tmp_path
):
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.secure_docker_argv(
            [command, *network_pull_options, IMAGE, "true"],
            run_prefix="nhpub-volume-normalize-test",
            owner_token="normalize-token",
            image=IMAGE,
            snapshot_script=tmp_path / "sqlite_snapshot.py",
        )


@pytest.mark.parametrize("owner_label_options", [
    ["--label", f"{acceptance.OWNER_LABEL}=other-token"],
    [f"--label={acceptance.OWNER_LABEL}=other-token"],
    ["--label", f"{acceptance.OWNER_LABEL}=first", "--label", f"{acceptance.OWNER_LABEL}=second"],
    [f"--label={acceptance.OWNER_LABEL}=first", f"--label={acceptance.OWNER_LABEL}=second"],
    ["--label", acceptance.OWNER_LABEL],
    [f"--label={acceptance.OWNER_LABEL}"],
    ["--label", f"{acceptance.OWNER_LABEL}=", "--label", f"{acceptance.OWNER_LABEL}=other-token"],
])
def test_secure_docker_rejects_any_user_supplied_owner_label(owner_label_options, tmp_path):
    with pytest.raises(acceptance.AcceptanceError, match="reserved ownership labels"):
        acceptance.secure_docker_argv(
            ["create", *owner_label_options, IMAGE, "true"],
            run_prefix="nhpub-volume-normalize-test",
            owner_token="runner-token",
            image=IMAGE,
            snapshot_script=tmp_path / "sqlite_snapshot.py",
        )


def test_secure_docker_does_not_parse_owner_label_lookalikes_after_image(tmp_path):
    tail = [
        IMAGE, "python", "-c", "pass",
        "--label", f"{acceptance.OWNER_LABEL}=application-arg",
        f"--label={acceptance.OWNER_LABEL}=application-arg-equal",
    ]
    rewritten = acceptance.secure_docker_argv(
        ["run", *tail],
        run_prefix="nhpub-volume-normalize-test",
        owner_token="runner-token",
        image=IMAGE,
        snapshot_script=tmp_path / "sqlite_snapshot.py",
    )
    assert rewritten[rewritten.index(IMAGE):] == tail


def test_secure_docker_does_not_treat_environment_value_as_owner_label(tmp_path):
    tail = [IMAGE, "python", "-c", "pass"]
    rewritten = acceptance.secure_docker_argv(
        ["run", "--env", f"APP_HINT=--label={acceptance.OWNER_LABEL}", *tail],
        run_prefix="nhpub-volume-normalize-test",
        owner_token="runner-token",
        image=IMAGE,
        snapshot_script=tmp_path / "sqlite_snapshot.py",
    )
    assert rewritten[rewritten.index(IMAGE):] == tail


@pytest.mark.parametrize(
    "command",
    [
        ["run", "--rm", "-p", "443:443", IMAGE, "true"],
        ["run", "--rm", "-p443:443", IMAGE, "true"],
        ["run", "--rm", "--publish-all", IMAGE, "true"],
        ["run", "--rm", "--network", "host", IMAGE, "true"],
        ["run", "--rm", "--net=host", IMAGE, "true"],
        ["run", "--rm", "--pull", "always", IMAGE, "true"],
        ["run", "--rm", "--mount", "type=volume,source=user-db,target=/fixture", IMAGE, "true"],
        ["run", "--rm", "--mount", "type=bind,source=/home/user/db.sqlite3,target=/fixture/db.sqlite3", IMAGE, "true"],
        ["run", "--rm", "--volume=/home/user/db.sqlite3:/fixture/db.sqlite3", IMAGE, "true"],
        ["run", "--rm", "--user", "0:0", "--mount", "type=volume,source=nhpub-volume-x-source,target=/fixture", IMAGE,
         "-c", "import os; os.chown('/fixture',0,0)"],
        ["run", "--rm", IMAGE + "-other", "true"],
        ["rm", "-f", "not-owned-container-id"],
    ],
)
def test_secure_docker_policy_rejects_unowned_resources_and_privileged_escape(command, tmp_path):
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.secure_docker_argv(
            command,
            run_prefix="nhpub-volume-test",
            owner_token="test-token",
            image=IMAGE,
            snapshot_script=tmp_path / "sqlite_snapshot.py",
            ledger_entries=[],
        )


def test_secure_docker_policy_only_chowns_owned_empty_volume_with_exact_code(tmp_path):
    prefix = "nhpub-volume-test"
    volume = prefix + "-source"
    command = acceptance.secure_docker_argv(
        [
            "run", "--user", "0:0", "--mount", f"type=volume,source={volume},target=/fixture",
            IMAGE, "-c", acceptance.ROOT_CHOWN_CODE,
        ],
        run_prefix=prefix,
        owner_token="token",
        image=IMAGE,
        snapshot_script=tmp_path / "sqlite_snapshot.py",
        ledger_entries=[{"kind": "volume", "name": volume}],
    )
    assert "0:0" in command


@pytest.mark.parametrize(
    "exec_args",
    [
        ["exec", "--user", "0:0", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "--user", "0:0", "a" * 64, "python", "-c", "print('external-container')"],
        ["exec", "--user=0:0", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "-u", "0:0", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "-u=0:0", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "--user", "10001:10001", "a" * 64, "python", "snapshot.py", "backup"],
        ["exec", "--user=10001:10001", "a" * 64, "python", "snapshot.py", "restore"],
        ["exec", "-u", "10001:10001", "a" * 64, "python", "snapshot.py", "backup"],
        ["exec", "-u=10001:10001", "a" * 64, "python", "snapshot.py", "restore"],
    ],
)
def test_secure_docker_policy_parses_formal_exec_user_options_before_owned_container(exec_args, tmp_path):
    rewritten = acceptance.secure_docker_argv(
        exec_args,
        run_prefix="nhpub-volume-test",
        owner_token="owner-token",
        image=IMAGE,
        snapshot_script=tmp_path / "sqlite_snapshot.py",
        ledger_entries=[{"kind": "container", "name": "nhpub-volume-test-c001", "id": "a" * 64}],
    )
    assert rewritten == exec_args


@pytest.mark.parametrize(
    "exec_args",
    [
        ["exec", "--user", "0:0", "external-container", "python", "-c", "prepare()"],
        ["exec", "--user", "999:999", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "--workdir", "/tmp", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "--user", "a" * 64, "python", "-c", "prepare()"],
        ["exec", "--user"],
        ["exec", "a" * 64],
    ],
)
def test_secure_docker_policy_rejects_unowned_or_unsupported_exec_operands(exec_args, tmp_path):
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.secure_docker_argv(
            exec_args,
            run_prefix="nhpub-volume-test",
            owner_token="owner-token",
            image=IMAGE,
            snapshot_script=tmp_path / "sqlite_snapshot.py",
            ledger_entries=[{"kind": "container", "name": "nhpub-volume-test-c001", "id": "a" * 64}],
        )


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_exit", "expected_id"),
    [("nonzero", "result_nonzero", 23, ""), ("timeout", "timeout", 124, ""), ("success", "created", 0, "b" * 64)],
)
def test_docker_proxy_persists_container_intent_before_failure_or_timeout(
    outcome, expected_status, expected_exit, expected_id, tmp_path, monkeypatch
):
    ledger = tmp_path / "resources.jsonl"
    command_log = tmp_path / "commands.jsonl"
    monkeypatch.setenv("NHVOL_REAL_DOCKER", "/usr/bin/docker")
    monkeypatch.setenv("NHVOL_PREFIX", "nhpub-volume-proxy-test")
    monkeypatch.setenv("NHVOL_OWNER_TOKEN", "proxy-test-token")
    monkeypatch.setenv("NHVOL_IMAGE", IMAGE)
    monkeypatch.setenv("NHVOL_SNAPSHOT_SCRIPT", "/repo/scripts/deploy/sqlite_snapshot.py")
    monkeypatch.setenv("NHVOL_LEDGER", str(ledger))
    monkeypatch.setenv("NHVOL_COMMAND_LOG", str(command_log))

    def fail_after_intent(argv, **kwargs):
        pending = acceptance._read_ledger(ledger)
        assert len(pending) == 1
        assert pending[0]["kind"] == "container"
        assert pending[0]["name"].startswith("nhpub-volume-proxy-test-")
        assert pending[0]["owner_label"] == acceptance.OWNER_LABEL
        assert pending[0]["owner_token"] == "proxy-test-token"
        assert pending[0]["state"] == "intent"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if outcome == "success":
            return subprocess.CompletedProcess(argv, 0, (expected_id + "\n").encode(), b"")
        return subprocess.CompletedProcess(argv, 23, b"", b"daemon rejected create")

    monkeypatch.setattr(acceptance.subprocess, "run", fail_after_intent)
    args = [
        "create", "--pull=never", "--network", "none", "--user", "10001:10001",
        IMAGE, "python", "-c", "pass",
    ]
    assert acceptance.docker_proxy_main(args) == expected_exit
    entries = acceptance._read_ledger(ledger)
    assert len(entries) == 1
    assert entries[0]["state"] == expected_status
    assert entries[0]["id"] == expected_id


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_exit"),
    [("nonzero", "result_nonzero", 23), ("timeout", "timeout", 124), ("success", "created", 0)],
)
def test_docker_proxy_persists_owned_volume_intent_before_result(outcome, expected_status, expected_exit, tmp_path, monkeypatch):
    ledger = tmp_path / "resources.jsonl"
    command_log = tmp_path / "commands.jsonl"
    volume = "nhpub-volume-proxy-test-source"
    monkeypatch.setenv("NHVOL_REAL_DOCKER", "/usr/bin/docker")
    monkeypatch.setenv("NHVOL_PREFIX", "nhpub-volume-proxy-test")
    monkeypatch.setenv("NHVOL_OWNER_TOKEN", "proxy-test-token")
    monkeypatch.setenv("NHVOL_IMAGE", IMAGE)
    monkeypatch.setenv("NHVOL_SNAPSHOT_SCRIPT", "/repo/scripts/deploy/sqlite_snapshot.py")
    monkeypatch.setenv("NHVOL_LEDGER", str(ledger))
    monkeypatch.setenv("NHVOL_COMMAND_LOG", str(command_log))

    def fake_run(argv, **kwargs):
        pending = acceptance._read_ledger(ledger)
        assert pending == [{
            "kind": "volume", "name": volume, "owner_label": acceptance.OWNER_LABEL,
            "owner_token": "proxy-test-token", "state": "intent",
        }]
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if outcome == "success":
            return subprocess.CompletedProcess(argv, 0, (volume + "\n").encode(), b"")
        return subprocess.CompletedProcess(argv, 23, b"", b"daemon rejected volume")

    monkeypatch.setattr(acceptance.subprocess, "run", fake_run)
    assert acceptance.docker_proxy_main(["volume", "create", volume]) == expected_exit
    assert acceptance._read_ledger(ledger) == [{
        "kind": "volume", "name": volume, "owner_label": acceptance.OWNER_LABEL,
        "owner_token": "proxy-test-token", "state": expected_status,
    }]


def test_cleanup_accepts_only_explicit_docker_not_found_for_pending_resources(tmp_path, monkeypatch):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    runner.report_dir.mkdir(mode=0o700)
    runner.token = "pending-token"
    runner.prefix = "nhpub-volume-pending-token"
    container_name = runner.prefix + "-c001"
    volume_name = runner.prefix + "-source"
    runner.ledger_path.write_text(
        '{"kind":"container","name":"' + container_name + '","id":"","owner_label":"' + acceptance.OWNER_LABEL + '","owner_token":"pending-token","state":"timeout"}\n'
        '{"kind":"volume","name":"' + volume_name + '","owner_label":"' + acceptance.OWNER_LABEL + '","owner_token":"pending-token","state":"result_nonzero"}\n',
        encoding="utf-8",
    )
    calls = []

    def fake_command(label, argv, *, timeout=180.0):
        calls.append(label)
        if label == "verify_owned_container_label":
            return subprocess.CompletedProcess(argv, 1, "", f"Error: No such object: {container_name}\n")
        if label == "verify_owned_volume_label":
            return subprocess.CompletedProcess(argv, 1, "", f"Error response: get {volume_name}: no such volume\n")
        raise AssertionError(f"unexpected cleanup command: {label}")

    monkeypatch.setattr(runner, "_command", fake_command)
    runner._cleanup()
    assert runner.report["resources"]["absent_containers"] == [container_name]
    assert runner.report["resources"]["absent_volumes"] == [volume_name]
    assert "remove_owned_container_id" not in calls
    assert "remove_owned_volume" not in calls


def test_cleanup_fails_closed_when_resource_inspection_is_not_explicit_not_found(tmp_path, monkeypatch):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    runner.report_dir.mkdir(mode=0o700)
    runner.token = "pending-token"
    runner.prefix = "nhpub-volume-pending-token"
    container_name = runner.prefix + "-c001"
    runner.ledger_path.write_text(
        '{"kind":"container","name":"' + container_name + '","id":"","owner_label":"' + acceptance.OWNER_LABEL + '","owner_token":"pending-token","state":"timeout"}\n',
        encoding="utf-8",
    )

    def fake_command(label, argv, *, timeout=180.0):
        return subprocess.CompletedProcess(argv, 1, "", "Docker daemon is unavailable\n")

    monkeypatch.setattr(runner, "_command", fake_command)
    with pytest.raises(acceptance.AcceptanceError, match="without explicit Docker not-found evidence"):
        runner._cleanup()


def test_cleanup_removes_only_ledgered_container_id_and_owned_volume(tmp_path, monkeypatch):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    runner.report_dir.mkdir(mode=0o700)
    runner.token = "owned-token"
    runner.prefix = "nhpub-volume-owned-token"
    container_name = runner.prefix + "-c001"
    container_id = "c" * 64
    volume_name = runner.prefix + "-source"
    runner.ledger_path.write_text(
        "\n".join(
            (
                '{"kind":"container","name":"' + container_name + '","id":"' + container_id + '","owner_label":"' + acceptance.OWNER_LABEL + '","owner_token":"owned-token"}',
                '{"kind":"volume","name":"' + volume_name + '","owner_label":"' + acceptance.OWNER_LABEL + '","owner_token":"owned-token"}',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, list[str]]] = []

    def fake_command(label, argv, *, timeout=180.0):
        args = list(argv)
        calls.append((label, args))
        if label == "verify_owned_container_label":
            return subprocess.CompletedProcess(args, 0, "owned-token\n", "")
        if label == "resolve_owned_container_id":
            return subprocess.CompletedProcess(args, 0, container_id + "\n", "")
        if label == "verify_owned_volume_label":
            return subprocess.CompletedProcess(args, 0, "owned-token\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(runner, "_command", fake_command)
    runner._cleanup()

    assert ("remove_owned_container_id", ["docker", "rm", "-f", container_id]) in calls
    assert ("remove_owned_volume", ["docker", "volume", "rm", volume_name]) in calls
    all_args = [arg for _, argv in calls for arg in argv]
    assert "user-db" not in all_args
    assert runner.report["resources"]["cleaned_container_ids"] == [container_id]
    assert runner.report["resources"]["cleaned_volumes"] == [volume_name]


def _write_fake_docker(path: Path, events: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['NHVOL_FAKE_DOCKER_EVENTS'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps({'args': args}) + '\\n')\n"
        "if args[:2] == ['container', 'inspect']:\n"
        "    format_arg = args[3]\n"
        "    if 'Config.Labels' in format_arg:\n"
        "        print(os.environ['NHVOL_FAKE_DOCKER_OWNER_LABEL'])\n"
        "    elif format_arg == '{{.Id}}':\n"
        "        print(os.environ['NHVOL_FAKE_DOCKER_CONTAINER_ID'])\n"
        "    else:\n"
        "        sys.exit(90)\n"
        "elif args and args[0] == 'rm':\n"
        "    with open(os.environ['NHVOL_LEDGER'], encoding='utf-8') as stream:\n"
        "        entries = [json.loads(line) for line in stream if line.strip()]\n"
        "    if not any(entry.get('id') == args[-1] and entry.get('owner_token') == os.environ['NHVOL_OWNER_TOKEN'] for entry in entries):\n"
        "        sys.exit(91)\n"
        "else:\n"
        "    sys.exit(92)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _prepare_fake_cleanup_runner(tmp_path, monkeypatch, *, wrong_label=False):
    fake_docker = tmp_path / "fake-real-docker"
    events = tmp_path / "fake-docker-events.jsonl"
    _write_fake_docker(fake_docker, events)
    monkeypatch.setenv("NHVOL_FAKE_DOCKER_EVENTS", str(events))
    monkeypatch.setenv("NHVOL_FAKE_DOCKER_CONTAINER_ID", "d" * 64)
    monkeypatch.setattr(acceptance.shutil, "which", lambda name: str(fake_docker) if name == "docker" else None)

    runner = acceptance.AcceptanceRunner(options(tmp_path))
    monkeypatch.setenv("NHVOL_FAKE_DOCKER_OWNER_LABEL", "wrong-owner" if wrong_label else runner.token)
    runner._prepare_workspace()
    container_name = runner.prefix + "-c001"
    runner.ledger_path.write_text(
        json.dumps({
            "kind": "container",
            "name": container_name,
            "id": "",
            "owner_label": acceptance.OWNER_LABEL,
            "owner_token": runner.token,
            "state": "timeout",
        }) + "\n",
        encoding="utf-8",
    )
    return runner, events, container_name


def test_cleanup_timeout_container_id_is_persisted_before_secure_shim_removal(tmp_path, monkeypatch):
    runner, events, container_name = _prepare_fake_cleanup_runner(tmp_path, monkeypatch)
    container_id = "d" * 64

    runner._cleanup()

    assert acceptance._read_ledger(runner.ledger_path)[0]["id"] == container_id
    recorded_calls = [json.loads(line)["args"] for line in events.read_text(encoding="utf-8").splitlines()]
    assert recorded_calls == [
        ["container", "inspect", "--format", f'{{{{ index .Config.Labels "{acceptance.OWNER_LABEL}" }}}}', container_name],
        ["container", "inspect", "--format", "{{.Id}}", container_name],
        ["rm", "-f", container_id],
    ]
    assert runner.report["resources"]["cleaned_container_ids"] == [container_id]


def test_cleanup_wrong_label_never_persists_id_or_removes_container_through_shim(tmp_path, monkeypatch):
    runner, events, _container_name = _prepare_fake_cleanup_runner(tmp_path, monkeypatch, wrong_label=True)
    container_id = "d" * 64

    with pytest.raises(acceptance.AcceptanceError, match="refused to remove container"):
        runner._cleanup()

    assert acceptance._read_ledger(runner.ledger_path)[0]["id"] == ""
    recorded_calls = [json.loads(line)["args"] for line in events.read_text(encoding="utf-8").splitlines()]
    assert len(recorded_calls) == 1
    assert recorded_calls[0][0:2] == ["container", "inspect"]
    assert all(args[0] != "rm" or args[-1] != container_id for args in recorded_calls)


@pytest.mark.parametrize("race", ["directory", "symlink"])
def test_run_does_not_write_or_chmod_a_competing_report_path(tmp_path, monkeypatch, race):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    report_dir = runner.report_dir
    sentinel_dir = tmp_path / "existing-evidence"
    sentinel_dir.mkdir(mode=0o700)
    report_file = sentinel_dir / "report.json"
    report_file.write_bytes(b"preserve competing report\n")
    report_file.chmod(0o640)
    sentinel_dir.chmod(0o751)

    if race == "directory":
        report_dir.mkdir(mode=0o711)
        report_dir.chmod(0o711)
        existing_dir = report_dir
        report_file = report_dir / "report.json"
        report_file.write_bytes(b"preserve competing report\n")
        report_file.chmod(0o640)
    else:
        report_dir.symlink_to(sentinel_dir, target_is_directory=True)
        existing_dir = sentinel_dir

    existing_mode = stat.S_IMODE(existing_dir.stat().st_mode)
    existing_file_mode = stat.S_IMODE(report_file.stat().st_mode)
    monkeypatch.setattr(runner, "_cleanup", lambda: pytest.fail("cleanup must not run without owned workspace"))

    assert runner.run() == 1
    assert report_file.read_bytes() == b"preserve competing report\n"
    assert stat.S_IMODE(existing_dir.stat().st_mode) == existing_mode
    assert stat.S_IMODE(report_file.stat().st_mode) == existing_file_mode
    assert sorted(path.name for path in existing_dir.iterdir()) == ["report.json"]
    if race == "symlink":
        assert report_dir.is_symlink()
        assert report_dir.resolve() == sentinel_dir.resolve()
    else:
        assert stat.S_IMODE(report_dir.stat().st_mode) == 0o711


def test_run_stops_writing_and_skips_cleanup_after_owned_workspace_becomes_symlink(tmp_path, monkeypatch):
    runner = acceptance.AcceptanceRunner(options(tmp_path))
    runner.real_docker = "/unused/fake-docker"
    sentinel_dir = tmp_path / "evidence-target"
    sentinel_dir.mkdir(mode=0o751)
    sentinel = sentinel_dir / "report.json"
    sentinel.write_bytes(b"preserve evidence\n")
    sentinel.chmod(0o640)
    original_dir_mode = stat.S_IMODE(sentinel_dir.stat().st_mode)
    original_file_mode = stat.S_IMODE(sentinel.stat().st_mode)
    displaced_workspace = tmp_path / "displaced-owned-workspace"
    prepare_workspace = runner._prepare_workspace

    def prepare_then_replace_with_symlink():
        prepare_workspace()
        runner.report_dir.rename(displaced_workspace)
        runner.report_dir.symlink_to(sentinel_dir, target_is_directory=True)

    monkeypatch.setattr(runner, "_prepare_workspace", prepare_then_replace_with_symlink)
    monkeypatch.setattr(runner, "_cleanup", lambda: pytest.fail("cleanup must not use a replaced workspace"))

    assert runner.run() == 1
    assert runner.report_dir.is_symlink()
    assert sentinel.read_bytes() == b"preserve evidence\n"
    assert stat.S_IMODE(sentinel_dir.stat().st_mode) == original_dir_mode
    assert stat.S_IMODE(sentinel.stat().st_mode) == original_file_mode
    assert sorted(path.name for path in sentinel_dir.iterdir()) == ["report.json"]
    assert not (displaced_workspace / "report.json").exists()
