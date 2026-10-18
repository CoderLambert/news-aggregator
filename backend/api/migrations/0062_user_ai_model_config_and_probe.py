"""T02: model configuration and durable, owner-scoped probe receipts.

Forward-only application migration: model rows do not contain credentials.
The preceding 0061 retirement contract and all historical data remain intact.
"""
import uuid
import re

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion



# These old model names were preserved by 0061 as non-executable metadata.
# Import only safe model IDs; invalid originals remain on the connection row
# for manual operator review rather than being silently promoted to routing.
_ALLOWED_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}
    dependencies = [
        ('api', '0061_retire_legacy_byok'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserAIModelConfig',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('model_id', models.CharField(max_length=160)),
                ('display_name', models.CharField(max_length=64)),
                ('catalog_model_id', models.CharField(blank=True, default='', max_length=80)),
                ('config_revision', models.PositiveBigIntegerField(default=1)),
                ('capability_results', models.JSONField(default=dict)),
                ('last_text_attempt', models.UUIDField(blank=True, null=True)),
                ('last_tools_attempt', models.UUIDField(blank=True, null=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='model_configs', to='api.useraiconnection')),
            ],
            options={'ordering': ['created_at', 'id']},
        ),
        migrations.AddConstraint(
            model_name='useraimodelconfig',
            constraint=models.UniqueConstraint(
                fields=('connection', 'model_id'), condition=models.Q(is_deleted=False),
                name='user_ai_model_unique_active'),
        ),
        migrations.CreateModel(
            name='AIModelProbeAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_id', models.UUIDField()),
                ('model_id', models.CharField(max_length=160)),
                ('model_revision', models.PositiveBigIntegerField()),
                ('probe_kind', models.CharField(max_length=8)),
                ('status', models.CharField(default='started', max_length=16)),
                ('safe_error_code', models.CharField(blank=True, default='', max_length=48)),
                ('credential_epoch', models.PositiveBigIntegerField()),
                ('credential_version', models.PositiveBigIntegerField()),
                ('endpoint_profile', models.CharField(max_length=48)),
                ('endpoint_profile_version', models.PositiveSmallIntegerField()),
                ('proxy_alias', models.CharField(max_length=80)),
                ('provider_request_id', models.CharField(blank=True, default='', max_length=128)),
                ('input_tokens', models.PositiveIntegerField(blank=True, null=True)),
                ('output_tokens', models.PositiveIntegerField(blank=True, null=True)),
                ('latency_ms', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    to='api.useraiconnection')),
                ('model_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='probe_attempts', to='api.useraimodelconfig')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at', 'id'],
                'indexes': [models.Index(fields=['user', 'created_at'], name='ai_probe_owner_created')],
                'constraints': [models.UniqueConstraint(fields=('user', 'request_id'), name='ai_probe_request_unique')]},
        ),
    ]
)
_PREFIX = {
    'openai': 'openai', 'anthropic': 'anthropic', 'deepseek': 'deepseek',
    'gemini': 'gemini', 'qwen': 'dashscope', 'glm': 'zai',
    'kimi': 'moonshot', 'mistral': 'mistral', 'groq': 'groq',
    'xai': 'xai', 'openrouter': 'openrouter',
}


def _import_inert_model_selection(apps, schema_editor):
    Connection = apps.get_model('api', 'UserAIConnection')
    Model = apps.get_model('api', 'UserAIModelConfig')
    db = schema_editor.connection.alias
    for connection in Connection.objects.using(db).exclude(imported_model_id='').iterator():
        raw = connection.imported_model_id
        if (not isinstance(raw, str) or raw != raw.strip()
                or not _ALLOWED_ID.fullmatch(raw) or '://' in raw or '..' in raw
                or '//' in raw or raw.lower().startswith(('sk-', 'ark-', 'aiza'))):
            continue
        prefix = _PREFIX.get(connection.provider_id)
        if prefix is None:
            continue
        model_id = raw[len(prefix) + 1:] if raw.startswith(prefix + '/') else raw
        if not model_id or not _ALLOWED_ID.fullmatch(model_id):
            continue
        Model.objects.using(db).get_or_create(
            connection_id=connection.pk, model_id=model_id,
            defaults={'display_name': model_id[:64], 'catalog_model_id': '',
                      'capability_results': {}},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0061_retire_legacy_byok'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserAIModelConfig',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('model_id', models.CharField(max_length=160)),
                ('display_name', models.CharField(max_length=64)),
                ('catalog_model_id', models.CharField(blank=True, default='', max_length=80)),
                ('config_revision', models.PositiveBigIntegerField(default=1)),
                ('capability_results', models.JSONField(default=dict)),
                ('last_text_attempt', models.UUIDField(blank=True, null=True)),
                ('last_tools_attempt', models.UUIDField(blank=True, null=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='model_configs', to='api.useraiconnection')),
            ],
            options={'ordering': ['created_at', 'id']},
        ),
        migrations.AddConstraint(
            model_name='useraimodelconfig',
            constraint=models.UniqueConstraint(
                fields=('connection', 'model_id'), condition=models.Q(is_deleted=False),
                name='user_ai_model_unique_active'),
        ),
        migrations.CreateModel(
            name='AIModelProbeAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_id', models.UUIDField()),
                ('model_id', models.CharField(max_length=160)),
                ('model_revision', models.PositiveBigIntegerField()),
                ('probe_kind', models.CharField(max_length=8)),
                ('status', models.CharField(default='started', max_length=16)),
                ('safe_error_code', models.CharField(blank=True, default='', max_length=48)),
                ('credential_epoch', models.PositiveBigIntegerField()),
                ('credential_version', models.PositiveBigIntegerField()),
                ('endpoint_profile', models.CharField(max_length=48)),
                ('endpoint_profile_version', models.PositiveSmallIntegerField()),
                ('proxy_alias', models.CharField(max_length=80)),
                ('provider_request_id', models.CharField(blank=True, default='', max_length=128)),
                ('input_tokens', models.PositiveIntegerField(blank=True, null=True)),
                ('output_tokens', models.PositiveIntegerField(blank=True, null=True)),
                ('latency_ms', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    to='api.useraiconnection')),
                ('model_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='probe_attempts', to='api.useraimodelconfig')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at', 'id'],
                'indexes': [models.Index(fields=['user', 'created_at'], name='ai_probe_owner_created')],
                'constraints': [models.UniqueConstraint(fields=('user', 'request_id'), name='ai_probe_request_unique')]},
        ),
        migrations.RunPython(_import_inert_model_selection, migrations.RunPython.noop),
    ]
