"""Linux-only Vite launcher; no package installation or application DB access."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / 'frontend'
VITE = FRONTEND / 'node_modules/vite/bin/vite.js'
HOST = '127.0.0.1'


class LaunchError(Exception):
    pass


def state_path():
    instance = os.environ.get('NEWSHUB_DEV_INSTANCE', 'frontend')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', instance):
        raise LaunchError('NEWSHUB_DEV_INSTANCE must be 1..48 letters, digits, _ or -.')
    default = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'newshub-dev'
    base = Path(os.environ.get('NEWSHUB_DEV_STATE_DIR', str(default)))
    if not base.is_absolute() or base == Path('/') or base.resolve() != base:
        raise LaunchError('State directory must be an absolute, non-symlink path other than /.')
    key = hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:16]
    return base / f'{key}-{instance}'


def private_directory(path):
    if path.is_symlink():
        raise LaunchError('Refusing symlink state directory.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LaunchError('Managed state directory must be owned by this user with mode 0700.')


def safe_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise LaunchError('Managed state files must be private regular files owned by this user.')
    return fd


@contextlib.contextmanager
def locked_state(directory):
    private_directory(directory.parent)
    private_directory(directory)
    fd = safe_open(directory / 'control.lock', os.O_CREAT | os.O_RDWR)
    try:
        # Serializes start/stop/restart; no broad process-name matching.
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def fingerprint(pid):
    if type(pid) is not int or pid <= 1:
        return None
    try:
        proc = Path('/proc') / str(pid)
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z' or proc.stat().st_uid != os.getuid():
            return None
        return {
            'pid': pid, 'start': fields[19],
            'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'exe': os.readlink(proc / 'exe'),
            'cwd': os.readlink(proc / 'cwd'),
            'argv': (proc / 'cmdline').read_bytes().split(b'\0')[:-1],
        }  # argv is converted below before persistence
    except (OSError, IndexError, ValueError):
        return None


def identity(pid):
    value = fingerprint(pid)
    if value is not None:
        value['argv'] = [os.fsdecode(item) for item in value['argv']]
    return value


def load_record(directory):
    try:
        fd = safe_open(directory / 'process.json', os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd) as handle:
        try:
            value = json.load(handle)
        except (ValueError, UnicodeError):
            raise LaunchError('Invalid process record; refusing to signal any process.') from None
    if (not isinstance(value, dict) or not isinstance(value.get('identity'), dict)
            or type(value.get('port')) is not int or not 1024 <= value['port'] <= 65535
            or not isinstance(value.get('target'), str)):
        raise LaunchError('Invalid process record; refusing to signal any process.')
    process = value['identity']
    if (type(process.get('pid')) is not int or process['pid'] <= 1
            or not isinstance(process.get('argv'), list)
            or not all(isinstance(arg, str) for arg in process['argv'])
            or not all(isinstance(process.get(key), str) for key in ('start', 'boot', 'exe', 'cwd'))):
        raise LaunchError('Invalid process identity; refusing to signal any process.')
    return value


def owned(record):
    if not record or record.get('root') != str(ROOT):
        return False
    expected = record['identity']
    argv = expected.get('argv', [])
    return (isinstance(argv, list) and expected.get('cwd') == str(FRONTEND) and str(VITE) in argv
            and identity(expected.get('pid')) == expected)


def owns_listener(record):
    """Check the managed PID owns this exact loopback listener, not a stranger."""
    if not owned(record):
        return False
    try:
        proc = Path('/proc') / str(record['identity']['pid'])
        sockets = set()
        for entry in (proc / 'fd').iterdir():
            try:
                sockets.add(os.readlink(entry))
            except OSError:
                pass
        address = f'0100007F:{int(record["port"]):04X}'
        for line in (proc / 'net/tcp').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == address and fields[3] == '0A' and f'socket:[{fields[9]}]' in sockets:
                return True
    except (OSError, KeyError, ValueError, IndexError):
        pass
    return False


def node_command():
    requested = os.environ.get('NEWSHUB_DEV_NODE', 'node')
    node = shutil.which(requested)
    if not node:
        raise LaunchError('Node 22 is required; set NEWSHUB_DEV_NODE to an installed Node 22 executable.')
    result = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10)
    if result.returncode or not re.fullmatch(r'v22\.\d+\.\d+\s*', result.stdout):
        raise LaunchError('Node 22 is required; no runtime will be installed automatically.')
    if not VITE.is_file():
        raise LaunchError('Existing frontend/node_modules/vite is required; no dependencies will be installed.')
    # IPv4 matches the existing loopback-only backend mapping for localhost targets.
    # This repository's config is native ESM JavaScript. Avoid Vite's bundled
    # config temp files in shared node_modules; application cache stays per-instance.
    return [node, '--dns-result-order=ipv4first', str(VITE), '--configLoader', 'native']


def port_number():
    raw = os.environ.get('NEWSHUB_DEV_PORT', '5173')
    if not re.fullmatch(r'[0-9]{1,5}', raw) or not 1024 <= int(raw) <= 65535:
        raise LaunchError('NEWSHUB_DEV_PORT must be an unprivileged port (1024..65535).')
    return int(raw)


def save_record(directory, record):
    fd = safe_open(directory / 'process.json.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, 'w') as handle:
        json.dump(record, handle)
    os.replace(directory / 'process.json.tmp', directory / 'process.json')


def terminate(record):
    """Pin the process with pidfd before identity checks; never signal a reused PID."""
    if not record:
        return
    try:
        fd = os.pidfd_open(record['identity']['pid'])
    except ProcessLookupError:
        return
    try:
        if not owned(record):
            raise LaunchError('Process identity mismatch; refusing to signal it.')
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        if not select.select([fd], [], [], 8)[0]:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
            if not select.select([fd], [], [], 2)[0]:
                raise LaunchError('Managed process did not exit; process record retained.')
    except ProcessLookupError:
        pass
    finally:
        os.close(fd)


def stop(directory):
    record = load_record(directory)
    if not record:
        print('Vite 未运行')
        return
    if not owned(record):
        # A stale/reused PID is never signalled, including via restart.
        raise LaunchError('Stale or foreign process record; no process was stopped. Inspect/remove this record only: '
                          + str(directory / 'process.json'))
    terminate(record)
    (directory / 'process.json').unlink()
    print('Vite 已停止')


def start(directory):
    command = node_command()
    port = port_number()
    target = os.environ.get('NEWSHUB_DEV_API_TARGET', 'http://127.0.0.1:9527')
    record = load_record(directory)
    if record:
        if not owned(record):
            raise LaunchError('Stale or foreign process record; inspect it before starting: ' + str(directory / 'process.json'))
        if record['port'] == port and record.get('target') == target and owns_listener(record):
            print(f'Vite 已在运行 http://{HOST}:{port} (PID {record["identity"]["pid"]})')
            return
        raise LaunchError('This instance has different settings or is unhealthy; inspect it and use restart explicitly.')
    with socket.socket() as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            raise LaunchError(f'Port {port} is unavailable; no process was started.') from None
    command += ['--host', HOST, '--port', str(port), '--strictPort']
    environment = dict(os.environ, NEWSHUB_DEV_CACHE_DIR=str(directory / 'vite-cache'))
    log_fd = safe_open(directory / 'vite.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        child = subprocess.Popen(command, cwd=FRONTEND, stdin=subprocess.DEVNULL,
                                 stdout=log_fd, stderr=log_fd, start_new_session=True,
                                 env=environment)
    finally:
        os.close(log_fd)
    record = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise LaunchError(f'Vite exited ({child.returncode}); see {directory / "vite.log"}')
            current = identity(child.pid)
            if current and current['cwd'] == str(FRONTEND) and str(VITE) in current['argv']:
                record = {'root': str(ROOT), 'identity': current, 'port': port, 'target': target}
                if owns_listener(record):
                    save_record(directory, record)
                    print(f'Vite 已启动 http://{HOST}:{port} (PID {child.pid})\n日志: {directory / "vite.log"}')
                    return
            time.sleep(0.1)
        raise LaunchError('Vite did not acquire its requested listener within 15 seconds.')
    except BaseException:
        # Popen owns this un-reaped child, so its PID cannot be recycled yet.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        raise


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'help'
    actions = {'start', 'stop', 'restart', 'status', 'health', 'build', 'log'}
    if action not in actions:
        print('用法: news-dev {start|stop|restart|status|health|build|log}\n'
              '配置: NEWSHUB_DEV_NODE, NEWSHUB_DEV_PORT, NEWSHUB_DEV_API_TARGET, '
              'NEWSHUB_DEV_INSTANCE, NEWSHUB_DEV_STATE_DIR')
        return 0 if action in {'help', '--help', '-h'} else 2
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise LaunchError('Linux with Python pidfd support is required for safe process control.')
    directory = state_path()
    if action == 'build':
        return subprocess.run(node_command() + ['build'], cwd=FRONTEND).returncode
    if action in {'status', 'health', 'stop', 'log'} and not directory.exists():
        print('Vite 未运行')
        return 1 if action in {'health', 'log'} else 0
    if action == 'log':
        private_directory(directory)
        fd = safe_open(directory / 'vite.log', os.O_RDONLY)
        with os.fdopen(fd) as handle:
            while True:
                chunk = handle.read(8192)
                if chunk:
                    print(chunk, end='', flush=True)
                else:
                    time.sleep(0.25)
    with locked_state(directory):
        if action in {'status', 'health'}:
            healthy = owns_listener(load_record(directory))
            print('Vite 运行正常' if healthy else 'Vite 未运行或身份/监听不匹配')
            return 0 if healthy or action == 'status' else 1
        if action in {'stop', 'restart'}:
            stop(directory)
        if action in {'start', 'restart'}:
            start(directory)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (LaunchError, OSError, subprocess.SubprocessError) as error:
        print(f'news-dev: {error}', file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
