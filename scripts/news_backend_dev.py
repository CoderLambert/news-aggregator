"""Explicit `news-server dev` mode, sharing news_dev's Linux process primitives."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
import warnings

import news_dev as control

ROOT = control.ROOT
BACKEND = ROOT / 'backend'
MANAGE = BACKEND / 'manage.py'
sys.path.insert(0, str(BACKEND))
from newsaggregator import dev_runtime as runtime  # noqa: E402


def state_path():
    return runtime.external_path(control.state_path() / 'backend')


def options():
    # Do not silently accept a path intended for the real database/runtime.
    if any(key in os.environ for key in runtime.PATH_VARIABLES):
        raise control.LaunchError('Do not supply application data paths to dev mode; all paths are task-owned.')
    api = runtime.port(os.environ.get('NEWSHUB_DEV_BACKEND_PORT', '29527'))
    ui = runtime.port(os.environ.get('NEWSHUB_DEV_FRONTEND_PORT', '25173'))
    if api == ui:
        raise control.LaunchError('Backend and frontend ports must differ.')
    return api, ui


def python_command(directory):
    requested = os.environ.get('NEWSHUB_DEV_PYTHON', str(BACKEND / 'venv/bin/python'))
    python = shutil.which(requested)
    if not python:
        raise control.LaunchError('Set NEWSHUB_DEV_PYTHON to an existing complete Python 3.12/CI-lock environment.')
    python = os.path.abspath(python)  # Keep the venv symlink, not its base interpreter.
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(directory / 'home')}
    probe = subprocess.run([python, '-I', '-B', '-c',
                            'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'],
                           env=env, capture_output=True, timeout=10)
    if probe.returncode:
        raise control.LaunchError('Python 3.12 is required; no runtime will be installed automatically.')
    check = subprocess.run([python, '-I', '-B', str(ROOT / 'ops/ci/check-backend-lock.py'),
                            str(BACKEND / 'requirements.txt'), str(BACKEND / 'requirements-ci.lock'),
                            '--installed'], env=env, capture_output=True, timeout=30)
    if check.returncode:
        raise control.LaunchError('Incomplete/incompatible CI-lock environment; validate with ops/ci/check-backend-lock.py --installed. No installation attempted.')
    return python


def read_key(*, prompt=False):
    """Only a dedicated private file or explicit hidden TTY prompt; never env values/argv."""
    path = os.environ.get('NEWSHUB_DEV_KEY_FILE')
    key = None
    if path:
        try:
            source = runtime.external_path(path)
            if source.name == '.env' or source.name.startswith('.env.'):
                raise ValueError('not a dedicated key file')
            fd = control.safe_open(source, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                    raise ValueError('private unlinked file required')
                raw = handle.read(4099)
                if len(raw) > 4098:
                    raise ValueError('oversized key file')
                key = raw.decode('ascii').rstrip('\r\n')
        except (OSError, ValueError, control.LaunchError):
            raise control.LaunchError('Key input must be a dedicated owned 0600 file outside Git, without links; input not logged.') from None
    elif prompt:
        if not sys.stdin.isatty():
            raise control.LaunchError('Use a private NEWSHUB_DEV_KEY_FILE or an interactive terminal for import-key.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                key = getpass.getpass('Development API Key (hidden): ')
        except (getpass.GetPassWarning, EOFError):
            raise control.LaunchError('Hidden key input unavailable; nothing imported.') from None
    if key is not None and (not 8 <= len(key) <= 4096 or any(ord(char) <= 32 or ord(char) >= 127 for char in key)):
        raise control.LaunchError('Invalid development key input; value not logged.')
    return key


def initialize(directory, python):
    key = read_key()
    marker = directory / 'instance.json'
    if not marker.exists():
        if set(path.name for path in directory.iterdir()) != {'control.lock'}:
            raise control.LaunchError('Unowned runtime files exist; refusing to adopt or migrate them.')
        value = {'kind': runtime.KIND, 'root': str(ROOT), 'directory': str(directory),
                 'id': str(uuid.uuid4()), 'secret': secrets.token_urlsafe(64)}
        fd = control.safe_open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
    runtime.read_instance(directory)
    for name in ('home', 'tmp', 'cache', 'media', 'chroma', 'tts'):
        control.private_directory(directory / name)
    run_manage(directory, python, ['migrate', '--noinput'], timeout=180)
    run_manage(directory, python, ['dev_bootstrap', '--key-stdin'], timeout=60, key=key, show_output=True)
    print(f'独立开发默认配置已初始化/保留: {directory / "db.sqlite3"}')


def run_manage(directory, python, args, timeout, *, key=None, show_output=False):
    api, ui = options()
    env = runtime.environment(directory, api, ui)
    fd = control.safe_open(directory / 'django.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        # Secret contents travel only through a private stdin pipe, not argv/env/logs.
        incoming = {'input': (key or '').encode('ascii')} if '--key-stdin' in args else {'stdin': subprocess.DEVNULL}
        result = subprocess.run([python, '-B', str(MANAGE), *args, f'--settings={runtime.PROFILE}'],
                                cwd=BACKEND, env=env, **incoming,
                                stdout=subprocess.PIPE if show_output else fd, stderr=fd, timeout=timeout, umask=0o077)
        if show_output and result.stdout:
            os.write(fd, result.stdout)
            print(result.stdout.decode('utf-8', errors='replace'), end='')
    finally:
        os.close(fd)
    if result.returncode:
        raise control.LaunchError(f'Django command failed ({result.returncode}); see {directory / "django.log"}')


def owned(record):
    if not record or record.get('root') != str(ROOT):
        return False
    expected = record['identity']
    argv = expected['argv']
    required = [str(MANAGE), 'runserver', f'127.0.0.1:{record["port"]}', f'--settings={runtime.PROFILE}']
    if (expected['cwd'] != str(BACKEND) or argv[-4:] != required
            or control.identity(expected['pid']) != expected):
        return False
    parent = record.get('parent')
    if parent:
        if not owned({key: value for key, value in (record | {'identity': parent}).items() if key != 'parent'}):
            return False
        try:
            fields = (Path('/proc') / str(expected['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
            return int(fields[1]) == parent['pid'] and int(fields[3]) == parent['pid']
        except (OSError, ValueError, IndexError):
            return False
    return True


def family(record):
    if not owned(record):
        raise control.LaunchError('Stale or foreign backend identity; no process was signalled.')
    children = (Path('/proc') / str(record['identity']['pid']) / 'task'
                / str(record['identity']['pid']) / 'children').read_text().split()
    result = [record]
    for pid in children:
        identity = control.identity(int(pid))
        if identity is None:
            continue
        child = record | {'identity': identity, 'parent': record['identity']}
        if not owned(child):
            raise control.LaunchError('Unrecognized backend child; refusing process control.')
        result.append(child)
    return result


def healthy(record):
    try:
        return any(control.owns_listener(member, owned) for member in family(record))
    except (control.LaunchError, OSError):
        return False


def terminate_family(record):
    """Freeze the verified reloader before enumerating and pinning its children.

No killpg/pkill: each signal uses a pidfd plus exact identity/parent/session.
The frozen parent cannot spawn a replacement while its child is being stopped.
"""
    if not owned(record):
        raise control.LaunchError('Stale or foreign backend identity; no process was signalled.')
    fd = os.pidfd_open(record['identity']['pid'])
    frozen = False
    try:
        if not owned(record):
            raise control.LaunchError('Backend identity changed; refusing to signal it.')
        signal.pidfd_send_signal(fd, signal.SIGSTOP)
        frozen = True
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = (Path('/proc') / str(record['identity']['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()[0]
            if state in {'T', 't'}:
                break
            time.sleep(0.01)
        else:
            raise control.LaunchError('Reloader did not stop spawning; refusing child control.')
        for child in family(record)[1:]:
            control.terminate(child, owned)
        # Queue termination before resuming, so a pending reload cannot replace the child.
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        signal.pidfd_send_signal(fd, signal.SIGCONT)
        frozen = False
        if not select.select([fd], [], [], 8)[0]:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
            if not select.select([fd], [], [], 2)[0]:
                raise control.LaunchError('Reloader did not exit; record retained.')
    finally:
        if frozen:
            try:
                signal.pidfd_send_signal(fd, signal.SIGCONT)
            except ProcessLookupError:
                pass
        os.close(fd)


def record_at(directory):
    record = control.load_record(directory)
    if record and record.get('directory') != str(directory):
        raise control.LaunchError('Process record belongs to another instance; no process was signalled.')
    return record


def stop(directory):
    record = record_at(directory)
    if record:
        terminate_family(record)
        (directory / 'process.json').unlink()
    print('独立 Django 已停止（数据保留）')


def start(directory, python):
    runtime.read_instance(directory)
    if not (directory / 'db.sqlite3').is_file():
        raise control.LaunchError('Run news-server dev init first; start never migrates implicitly.')
    api, ui = options()
    target = f'http://127.0.0.1:{ui}'
    record = record_at(directory)
    if record:
        if owned(record) and record['port'] == api and record['target'] == target and healthy(record):
            print(f'独立 Django 已在运行 http://127.0.0.1:{api}')
            return
        raise control.LaunchError('Existing backend record is stale, unhealthy or differently configured; inspect it before restart.')
    with socket.socket() as probe:
        # Match Django WSGIServer: allow our closed connections' TIME_WAIT,
        # never SO_REUSEPORT and never a second live listener.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', api))
        except OSError:
            raise control.LaunchError(f'Port {api} is unavailable; nothing was started.') from None
    command = [python, '-B', str(MANAGE), 'runserver', f'127.0.0.1:{api}', f'--settings={runtime.PROFILE}']
    env = runtime.environment(directory, api, ui)  # RUN_MAIN intentionally absent.
    fd = control.safe_open(directory / 'django.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        child = subprocess.Popen(command, cwd=BACKEND, env=env, stdin=subprocess.DEVNULL,
                                 stdout=fd, stderr=fd, start_new_session=True, umask=0o077)
    finally:
        os.close(fd)
    record = None
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise control.LaunchError(f'Django exited ({child.returncode}); see {directory / "django.log"}')
            identity = control.identity(child.pid)
            if identity:
                record = {'root': str(ROOT), 'directory': str(directory), 'identity': identity, 'port': api, 'target': target}
                if healthy(record):
                    control.save_record(directory, record)
                    print(f'独立 Django: http://127.0.0.1:{api}\nCSRF/Vite: {target}\n日志: {directory / "django.log"}')
                    return
            time.sleep(0.1)
        raise control.LaunchError(f'Django did not acquire its listener; see {directory / "django.log"}')
    except BaseException:
        if record and owned(record):
            terminate_family(record)
        elif child.poll() is None:
            child.terminate()  # Still our unreaped Popen child, before Django exec/setup.
            child.wait(timeout=10)
        raise


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'help'
    if action not in {'init', 'import-key', 'start', 'stop', 'restart', 'status', 'health', 'log'}:
        print('用法: news-server dev {init|import-key|start|stop|restart|status|health|log}\n'
              '配置: NEWSHUB_DEV_PYTHON, NEWSHUB_DEV_BACKEND_PORT, NEWSHUB_DEV_FRONTEND_PORT, '
              'NEWSHUB_DEV_INSTANCE, NEWSHUB_DEV_STATE_DIR, NEWSHUB_DEV_KEY_FILE')
        return 0 if action in {'help', '-h', '--help'} else 2
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise control.LaunchError('Linux pidfd support is required.')
    directory = state_path()
    if action in {'stop', 'status', 'health', 'log'} and not directory.exists():
        print('独立 Django 未运行')
        return 1 if action in {'health', 'log'} else 0
    # Create/validate the shared frontend state base before nested directories;
    # mkdir(parents=True) alone would create this ancestor with mode 0755.
    control.private_directory(directory.parent.parent)
    with control.locked_state(directory):
        if action == 'log':
            fd = control.safe_open(directory / 'django.log', os.O_RDONLY)
            with os.fdopen(fd, 'rb') as handle:
                # Bounded output, including when the byte window starts inside UTF-8.
                handle.seek(max(0, os.fstat(handle.fileno()).st_size - 32768))
                print(handle.read().decode('utf-8', errors='replace'), end='')
            return 0
        if action in {'status', 'health'}:
            ok = healthy(record_at(directory))
            print('独立 Django 运行正常' if ok else '独立 Django 未运行或身份/监听不匹配')
            return 0 if ok or action == 'status' else 1
        if action == 'stop':
            stop(directory)
            return 0
        options()
        python = python_command(directory)
        if action in {'init', 'import-key'}:
            if record_at(directory):
                raise control.LaunchError('Stop this instance before explicit init/import.')
            if action == 'init':
                initialize(directory, python)
            else:
                runtime.read_instance(directory)
                if not (directory / 'db.sqlite3').is_file():
                    raise control.LaunchError('Run dev init before importing a key.')
                run_manage(directory, python, ['dev_bootstrap', '--key-stdin', '--existing-only'],
                           timeout=60, key=read_key(prompt=True), show_output=True)
        else:
            if action == 'restart':
                # Validate state/settings before stopping the existing instance.
                runtime.environment(directory, *options())
                stop(directory)
            start(directory, python)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (control.LaunchError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'news-server dev: {error}', file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
