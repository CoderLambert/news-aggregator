import uuid

from django.conf import settings
import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0030_subscription_translation_task'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResearchRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('idempotency_key', models.CharField(max_length=64)),
                ('request_hash', models.CharField(max_length=64)),
                ('status', models.CharField(choices=[('queued', '排队中'), ('running', '运行中'), ('succeeded', '已完成'), ('failed', '失败'), ('cancelled', '已取消'), ('interrupted', '已中断')], db_index=True, default='queued', max_length=16)),
                ('run_token', models.UUIDField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('lease_expires_at', models.DateTimeField(blank=True, null=True)),
                ('last_event_sequence', models.PositiveBigIntegerField(default=0)),
                ('event_wire_bytes', models.PositiveBigIntegerField(default=0)),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('error_message', models.CharField(blank=True, default='', max_length=255)),
                ('queued_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='runs', to='api.researchsession')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='research_runs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('user', 'idempotency_key'), name='unique_research_run_user_key'),
                    models.UniqueConstraint(condition=models.Q(('status__in', ['queued', 'running'])), fields=('session',), name='one_active_research_run_per_session'),
                ],
                'indexes': [models.Index(fields=['session', '-queued_at'], name='research_run_session_queued')],
            },
        ),
        migrations.CreateModel(
            name='ResearchRunEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('sequence', models.PositiveBigIntegerField()),
                ('event_type', models.CharField(max_length=32)),
                ('data', models.JSONField(default=dict)),
                ('wire_bytes', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='api.researchrun')),
            ],
            options={
                'ordering': ['sequence'],
                'constraints': [models.UniqueConstraint(fields=('run', 'sequence'), name='unique_research_event_sequence')],
            },
        ),
    ]
