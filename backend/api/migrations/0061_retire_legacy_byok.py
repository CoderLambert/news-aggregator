"""Once-only, atomic v1 Key import, then remove the obsolete storage table.

Historical migrations 0033/0034 remain unchanged and runnable. If any source
row cannot be decrypted/verified, Django rolls back this entire migration,
including DeleteModel: no legacy ciphertext is silently discarded.
The old model selection is staging metadata for T02, not executable routing.
This migration is intentionally irreversible; restore a reviewed database
snapshot for rollback rather than resurrecting deprecated Key routes.
"""
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from django.conf import settings
from django.db import migrations, models
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ALLOWED = frozenset({
    'openai', 'anthropic', 'deepseek', 'gemini', 'qwen', 'glm', 'kimi',
    'mistral', 'groq', 'xai', 'openrouter',
})


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':')).encode('ascii')


def _material():
    master = getattr(settings, 'PROVIDER_CREDENTIAL_ENCRYPTION_KEY', '')
    if not isinstance(master, str) or not master:
        raise RuntimeError('Legacy BYOK migration refused: stable encryption key unavailable')
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=b'newshub-user-provider-credential-v1',
                info=b'provider-api-key-encryption').derive(master.encode('utf-8'))


def _recover(key, credential):
    try:
        data = credential.encrypted_api_key
        decoded = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
        if len(decoded) < 28:
            raise ValueError('short ciphertext')
        aad = f'provider-api-key:v1:{int(credential.user_id)}:{credential.provider}'.encode()
        plaintext = AESGCM(key).decrypt(decoded[:12], decoded[12:], aad).decode('utf-8')
        if not plaintext:
            raise ValueError('empty key')
        return plaintext
    except Exception:
        raise RuntimeError('Legacy BYOK migration refused: invalid encrypted legacy credential') from None


def _forward(apps, schema_editor):
    Legacy = apps.get_model('api', 'UserProviderCredential')
    Connection = apps.get_model('api', 'UserAIConnection')
    db = schema_editor.connection.alias
    if not Legacy.objects.using(db).exists():
        return
    key = _material()
    for old in Legacy.objects.using(db).order_by('user_id').iterator():
        if old.provider not in ALLOWED or not old.model_id:
            raise RuntimeError('Legacy BYOK migration refused: unknown provider or missing model')
        if Connection.objects.using(db).filter(user_id=old.user_id, is_deleted=False).count() >= 20:
            raise RuntimeError('Legacy BYOK migration refused: connection limit exceeded')
        plaintext = _recover(key, old)
        connection_id = uuid.uuid4()
        request_id = uuid.uuid5(uuid.NAMESPACE_URL,
                                f'newshub-t01-import-v1:{old.user_id}:{old.provider}')
        if Connection.objects.using(db).filter(
                user_id=old.user_id, request_id=request_id).exists():
            raise RuntimeError('Legacy BYOK migration refused: request identity collision')
        aad = _canonical({
            'purpose': 'newshub-ai-connection-v2',
            'owner': old.user_id, 'id': str(connection_id),
            'provider': old.provider, 'endpoint': f'{old.provider}_default',
            'endpoint_version': 1, 'credential_version': 1,
        })
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(key).encrypt(nonce, plaintext.encode(), aad)
        # Verify before the old row/table can be removed.
        if AESGCM(key).decrypt(nonce, encrypted, aad).decode() != plaintext:
            raise RuntimeError('Legacy BYOK migration refused: import verification failed')
        ciphertext = 'v2.' + base64.urlsafe_b64encode(nonce + encrypted).decode()
        request_hash = hmac.new(
            key, _canonical({'purpose': 'legacy-import-v1', 'owner': old.user_id,
                             'provider': old.provider, 'connection': str(connection_id)}),
            hashlib.sha256).hexdigest()
        row = Connection.objects.using(db).create(
            id=connection_id, user_id=old.user_id, provider_id=old.provider,
            endpoint_profile=f'{old.provider}_default', endpoint_profile_version=1,
            display_name=f'迁移的 {old.provider} 连接',
            credential_ciphertext=ciphertext, encryption_key_id='provider-hkdf-v1',
            request_id=request_id, request_hash=request_hash,
            imported_model_id=old.model_id, is_enabled=False,
        )
        # Imported credentials start disabled until T02 capability/model opt-in.
        Connection.objects.using(db).filter(pk=row.pk).update(
            created_at=old.created_at, updated_at=old.updated_at
        )


def _reverse_empty_only(apps, schema_editor):
    """Permit synthetic schema-history rehearsals, never discard imported Keys.

    Django recreates the legacy table before this reverse callback. Reversal
    is safe only when there are no imported credentials. A real downgrade must
    instead use the reviewed pre-migration snapshot and maintenance procedure.
    """
    Connection = apps.get_model('api', 'UserAIConnection')
    if Connection.objects.using(schema_editor.connection.alias).exclude(imported_model_id='').exists():
        raise RuntimeError('BYOK downgrade refused: imported credentials require snapshot restore')


class Migration(migrations.Migration):
    atomic = True
    dependencies = [('api', '0060_user_ai_connection')]
    operations = [
        migrations.AddField(
            model_name='useraiconnection', name='imported_model_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.RunPython(_forward, _reverse_empty_only),
        migrations.DeleteModel(name='UserProviderCredential'),
    ]
