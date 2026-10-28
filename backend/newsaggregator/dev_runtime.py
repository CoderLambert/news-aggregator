"""Stdlib-only contract for the explicit isolated source-development profile.

Not a sandbox for hostile edited Python. It prevents accidental use of existing
credentials/state and fails closed on external I/O in this opt-in profile only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
KIND = 'newshub-isolated-backend-v1'
PROFILE = 'newsaggregator.dev_settings'
PATH_VARIABLES = {
    'DJANGO_DB_PATH': 'db.sqlite3',
    'CHROMA_DATA_DIR': 'chroma',
    'TTS_CACHE_DIR': 'tts',
    'CHATGPT_DEPLOYMENT_INSTANCE_FILE': 'deployment-id',
    'FULL_CONTENT_WORKER_LOCK': 'full-content.lock',
    'FULL_CONTENT_WORKER_HEARTBEAT': 'full-content-heartbeat.json',
    'CHANNEL_WORKER_HEARTBEAT': 'channel-heartbeat.json',
    'SEARCH_INDEX_WORKER_LOCK': 'search-index.lock',
}


def port(value):
    if not str(value).isascii() or not str(value).isdigit() or not 1024 <= int(value) <= 65535:
        raise ValueError('Development ports must be integers in 1024..65535.')
    if int(value) in {9527, 19527}:
        raise ValueError('Existing acceptance ports 9527/19527 are reserved; choose a new port.')
    return int(value)


def external_path(path):
    path = Path(path)
    if not path.is_absolute() or path == Path('/') or path.resolve() != path:
        raise ValueError('Runtime path must be absolute and contain no symlinks.')
    if any((parent / '.git').exists() for parent in (path, *path.parents)):
        raise ValueError('Runtime data must live outside every Git worktree.')
    return path


def validate_tree(directory):
    """No foreign/symlink/hardlinked files, including SQLite WAL sidecars."""
    directory = external_path(directory)
    for path in (directory, *directory.rglob('*')):
        info = path.lstat()
        if (info.st_uid != os.getuid() or info.st_mode & 0o077
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise ValueError('Runtime contains non-private, linked or foreign files; refusing access.')
    return directory


def read_instance(directory):
    directory = validate_tree(directory)
    path = directory / 'instance.json'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd) as handle:
        value = json.load(handle)
    if (not isinstance(value, dict) or value.get('kind') != KIND or value.get('root') != str(ROOT)
            or value.get('directory') != str(directory) or not isinstance(value.get('id'), str)):
        raise ValueError('Runtime ownership does not match this worktree/directory.')
    uuid.UUID(value['id'])
    if not isinstance(value.get('secret'), str) or len(value['secret']) < 50:
        raise ValueError('Invalid isolated development secret.')
    return value


def environment(directory, api_port, ui_port):
    """Construct, never merge, the environment. No shell/provider/Gateway keys."""
    instance = read_instance(directory)
    api_port, ui_port = port(api_port), port(ui_port)
    if api_port == ui_port:
        raise ValueError('Backend and frontend ports must differ.')
    directory = Path(directory)
    env = {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
        'HOME': str(directory / 'home'), 'TMPDIR': str(directory / 'tmp'),
        'XDG_CACHE_HOME': str(directory / 'cache'), 'XDG_CONFIG_HOME': str(directory / 'home'),
        'HF_HOME': str(directory / 'cache/huggingface'), 'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1', 'ANONYMIZED_TELEMETRY': 'False',
        'PYTHONPATH': os.pathsep.join((str(ROOT / 'backend'), str(ROOT / 'crawler'))),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1',
        'DJANGO_SETTINGS_MODULE': PROFILE, 'NEWSHUB_SKIP_DOTENV': '1',
        'NEWSHUB_DEV_RUNTIME': str(directory), 'NEWSHUB_DEV_BACKEND_PORT': str(api_port),
        'NEWSHUB_DEV_FRONTEND_PORT': str(ui_port),
        'DJANGO_ENV': 'development', 'DJANGO_DEBUG': '1',
        'DJANGO_SECRET_KEY': instance['secret'], 'DJANGO_ALLOWED_HOSTS': '127.0.0.1',
        'DJANGO_CSRF_TRUSTED_ORIGINS': f'http://127.0.0.1:{ui_port},http://127.0.0.1:{api_port}',
        'NEWS_CRAWL_ONLY': '1', 'PUBLIC_SITE_MODE': 'full', 'PUBLIC_SIGNUP_ENABLED': '1',
        'SEMANTIC_SEARCH_ENABLED': '0', 'PUBLIC_AI_ENABLED': '0', 'AI_BYOK_ENABLED': '0', 'CHATGPT_PLAN_USAGE_ENABLED': '0',
        'CHATGPT_AUTH_MODE': 'disabled', 'CHATGPT_DEPLOYMENT_INSTANCE_ID': instance['id'],
        'FULL_CONTENT_WORKER_ENABLED': '0', 'FULL_CONTENT_AUTO_ENQUEUE_ENABLED': '0',
        'RSS_FULL_CONTENT_ENABLED': '0',
    }
    env.update({key: str(directory / relative) for key, relative in PATH_VARIABLES.items()})
    return env


def install_io_guard(api_port):
    """Fail early instead of calling RSS/Redis/Gateway/model/download services.

Django's own autoreload subprocess is the only permitted subprocess. This is an
accident guard, not protection from same-user code deliberately removing it.
"""
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.path.basename(os.fsdecode(args[0]))
            if name == '.env' or name.startswith('.env.'):
                raise OSError('Dotenv file access is disabled in isolated source development.')
        if event in {'socket.connect', 'socket.connect_ex', 'socket.sendto', 'socket.getaddrinfo',
                     'socket.gethostbyname', 'socket.gethostbyaddr', 'os.system'}:
            raise OSError('External I/O is disabled in isolated source development.')
        if event == 'socket.bind' and args[1] != ('127.0.0.1', api_port):
            raise OSError('Only the assigned loopback listener is allowed.')
        if event == 'subprocess.Popen':
            argv = args[1]
            if (not isinstance(argv, (list, tuple)) or args[0] != sys.executable
                    or str(ROOT / 'backend/manage.py') not in argv or 'runserver' not in argv
                    or f'127.0.0.1:{api_port}' not in argv or f'--settings={PROFILE}' not in argv):
                raise OSError('Only Django autoreload is allowed to spawn in isolated development.')
    sys.addaudithook(guard)
