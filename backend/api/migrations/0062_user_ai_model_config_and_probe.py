"""T02: model configuration and durable, owner-scoped probe receipts.

Forward-only application migration: model rows do not contain credentials.
The preceding 0061 retirement contract and all historical data remain intact.
"""
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


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
    ]
