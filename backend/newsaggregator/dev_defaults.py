"""Offline, opt-in dev bootstrap. No production models, migrations or auth bypass.

A private receipt binds immutable row IDs to this runtime. A pending receipt
never auto-adopts data after a crash: ambiguity stops initialization, not resets.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import connection as database, transaction

from api.ai_connection_models import UserAIConnection
from api.ai_connection_views import KeySerializer
from api.ai_model_models import UserAIModelConfig
from api.ai_preference_models import UserAITaskPreference
from api.services.ai_credentials import creation_digest, encrypt_credential, lock_owner
from api.services.ai_model_registry import get_trusted_preset, normalize_model_id
from api.services.ai_registry import get_profile
from . import dev_runtime as runtime

ACCOUNTS = ('admin', 'user')
# Public, deliberately weak synthetic-development default; never a production default.
DEFAULT_PASSWORD = '12345678'
PROVIDER = 'deepseek'
PROFILE = 'deepseek_default'
MODEL = 'deepseek-flash'
DISPLAY = 'DeepSeek development'
# Matches the existing deepseek/deepseek-flash Proxy route, not a new HTTP client.
API_BASE = 'https://api.deepseek.com'
RECEIPT = 'defaults.json'


class BootstrapError(Exception):
    """Only constant, non-secret codes are safe to display."""


def private_fd(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        os.close(fd)
        raise BootstrapError('private_bootstrap_file_required')
    return fd


def context():
    if (settings.SETTINGS_MODULE != runtime.PROFILE or settings.DJANGO_ENV != 'development'
            or os.environ.get('NEWS_CRAWL_ONLY') != '1'):
        raise BootstrapError('isolated_dev_profile_required')
    directory = Path(os.environ['NEWSHUB_DEV_RUNTIME'])
    instance = runtime.read_instance(directory)
    if (database.vendor != 'sqlite' or Path(database.settings_dict['NAME']) != directory / 'db.sqlite3'
            or settings.AI_BYOK_ENABLED or settings.PUBLIC_AI_ENABLED
            or settings.CHATGPT_AUTH_MODE != 'disabled' or settings.CHATGPT_PLAN_USAGE_ENABLED
            or settings.FULL_CONTENT_WORKER_ENABLED or settings.FULL_CONTENT_AUTO_ENQUEUE_ENABLED):
        raise BootstrapError('isolated_dev_boundary_required')
    if (directory / 'process.json').exists():
        raise BootstrapError('stop_isolated_backend_before_bootstrap')
    return directory, instance


@contextmanager
def locked(directory):
    fd = private_fd(directory / 'defaults.lock', os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def read_receipt(directory, instance):
    try:
        fd = private_fd(directory / RECEIPT, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd) as handle:
        text = handle.read(16385)
    if len(text) > 16384:
        raise BootstrapError('bootstrap_receipt_invalid')
    value = json.loads(text)
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
            or value.get('runtime_id') != instance['id'] or value.get('state') != 'complete'
            or not isinstance(value.get('accounts'), dict) or set(value['accounts']) != set(ACCOUNTS)):
        raise BootstrapError('bootstrap_receipt_incomplete_or_foreign')
    return value


def write_receipt(directory, value):
    temporary = directory / (RECEIPT + '.tmp')
    fd = private_fd(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, directory / RECEIPT)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def owned_rows(receipt):
    rows = []
    for name in ACCOUNTS:
        ids = receipt['accounts'][name]
        if (not isinstance(ids, dict) or set(ids) != {'user_id', 'joined', 'connection_id', 'request_id', 'model_id'}
                or type(ids.get('user_id')) is not int or ids['user_id'] <= 0):
            raise BootstrapError('bootstrap_receipt_invalid')
        user = User.objects.filter(pk=ids['user_id'], username=name).first()
        conn = UserAIConnection.objects.filter(pk=ids['connection_id'], user=user).first() if user else None
        model = UserAIModelConfig.objects.filter(pk=ids['model_id'], connection=conn).first() if conn else None
        if (not user or user.date_joined.isoformat() != ids['joined'] or not conn or not model
                or str(conn.request_id) != ids['request_id'] or conn.is_deleted or model.is_deleted):
            raise BootstrapError('bootstrap_identity_conflict')
        if UserAIConnection.objects.filter(user=user, display_name=DISPLAY, is_deleted=False).exclude(pk=conn.pk).exists():
            raise BootstrapError('bootstrap_connection_name_conflict')
        rows.append((user, conn, model))
    return rows


def may_import(conn, model):
    profile = get_profile(PROVIDER, PROFILE)
    return bool(profile and not conn.is_enabled and not conn.is_deleted
        and conn.provider_id == PROVIDER and conn.endpoint_profile == PROFILE
        and conn.endpoint_profile_version == profile['version'] and not conn.endpoint_policy_digest
        and conn.auth_mode == 'api_key' and conn.display_name == DISPLAY
        and conn.revision == conn.credential_epoch == conn.credential_version == 1
        and not conn.credential_ciphertext and not conn.encryption_key_id
        and model.model_id == MODEL and model.config_revision == 1 and not model.is_deleted
        and not model.capability_results and model.last_text_attempt is None and model.last_tools_attempt is None
        and not conn.model_configs.exclude(pk=model.pk).exists()
        and not UserAITaskPreference.objects.filter(user_id=conn.user_id).exists())


def seed_defaults(api_key=None, *, existing_only=False):
    directory, instance = context()
    if api_key is not None:
        serializer = KeySerializer(data={'api_key': api_key})
        if not serializer.is_valid():
            raise BootstrapError('invalid_development_key')
        api_key = serializer.validated_data['api_key']
    if existing_only and api_key is None:
        raise BootstrapError('development_key_required')
    profile = get_profile(PROVIDER, PROFILE)
    if profile is None or normalize_model_id(PROVIDER, MODEL) != MODEL:
        raise BootstrapError('development_provider_contract_changed')
    with locked(directory):
        receipt = read_receipt(directory, instance)
        fresh = receipt is None
        if fresh:
            if existing_only:
                raise BootstrapError('initialize_development_defaults_first')
            if User.objects.filter(username__in=ACCOUNTS).exists():
                raise BootstrapError('unowned_development_account_conflict')
            # CPU-heavy password hashing and receipt I/O stay outside the DB transaction.
            passwords = {name: make_password(DEFAULT_PASSWORD) for name in ACCOUNTS}
            receipt = {'version': 1, 'runtime_id': instance['id'], 'state': 'pending', 'accounts': {}}
            write_receipt(directory, receipt)
        result = {'api_base': API_BASE, 'requested_model': MODEL, 'verification': 'not_run',
                  'network': 'disabled', 'task_bindings': 'unchanged', 'accounts': {}}
        with transaction.atomic():
            # SQLite writer reservation before reads, without updating any account.
            # SELECT FOR UPDATE alone does not serialize SQLite bootstrap writers.
            with database.cursor() as cursor:
                cursor.execute('UPDATE auth_user SET id=id WHERE 0')
            if fresh:
                if User.objects.filter(username__in=ACCOUNTS).exists():
                    raise BootstrapError('unowned_development_account_conflict')
                rows = []
                for name in ACCOUNTS:
                    user = User.objects.create(username=name, password=passwords[name], is_active=True,
                                               is_staff=name == 'admin', is_superuser=name == 'admin')
                    values = {'provider_id': PROVIDER, 'endpoint_profile': PROFILE, 'display_name': DISPLAY,
                              'auth_mode': 'api_key', 'api_key': api_key or ''}
                    conn = UserAIConnection(user=user, provider_id=PROVIDER, endpoint_profile=PROFILE,
                        endpoint_profile_version=profile['version'], display_name=DISPLAY,
                        request_hash=creation_digest(user.pk, values), is_enabled=False)
                    if api_key is not None:
                        conn.credential_ciphertext, conn.encryption_key_id = encrypt_credential(conn, api_key)
                    conn.save(force_insert=True)
                    model = UserAIModelConfig.objects.create(connection=conn, model_id=MODEL, display_name=MODEL,
                        catalog_model_id=MODEL if get_trusted_preset(conn, MODEL) else '')
                    receipt['accounts'][name] = {'user_id': user.pk, 'joined': user.date_joined.isoformat(),
                        'connection_id': str(conn.pk), 'request_id': str(conn.request_id), 'model_id': str(model.pk)}
                    rows.append((user, conn, model))
            else:
                rows = owned_rows(receipt)
                # Validate every missing-key candidate before changing either owner.
                for user, conn, model in rows:
                    if api_key is not None and not conn.credential_ciphertext:
                        if not may_import(conn, model):
                            raise BootstrapError('changed_or_revoked_connection_not_overwritten')
                        lock_owner(user.pk)
            for user, conn, model in rows:
                key_state = 'preserved' if conn.credential_ciphertext else 'missing'
                if api_key is not None and not fresh and not conn.credential_ciphertext:
                    conn.credential_epoch += 1
                    conn.credential_version += 1
                    conn.revision += 1
                    conn.credential_ciphertext, conn.encryption_key_id = encrypt_credential(conn, api_key)
                    conn.save(update_fields=['credential_epoch', 'credential_version', 'revision',
                                             'credential_ciphertext', 'encryption_key_id', 'updated_at'])
                    key_state = 'imported'
                elif fresh and api_key is not None:
                    key_state = 'imported'
                result['accounts'][user.username] = {'created': fresh, 'key': key_state,
                    'active': user.is_active, 'model_configuration': 'candidate_unverified' if fresh else 'preserved'}
        if fresh:
            receipt['state'] = 'complete'
            # Missing/incomplete completion receipts block adoption after failures.
            write_receipt(directory, receipt)
        return result
