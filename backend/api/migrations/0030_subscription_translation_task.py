import uuid

from django.conf import settings
import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0029_oauth_attempt_snapshot'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatGPTTranslationTask',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_hash', models.CharField(max_length=64)),
                ('model_slug', models.CharField(max_length=255)),
                ('connection_generation', models.PositiveBigIntegerField()),
                ('generation', models.PositiveBigIntegerField(default=1)),
                ('run_token', models.UUIDField(blank=True, null=True)),
                ('shared_lease_task_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('shared_lease_token', models.UUIDField(blank=True, null=True)),
                ('status', models.CharField(choices=[('queued', '排队中'), ('running', '运行中'), ('succeeded', '已完成'), ('failed', '失败'), ('cancelled', '已取消'), ('interrupted', '已中断')], db_index=True, default='queued', max_length=16)),
                ('provider_started', models.BooleanField(default=False)),
                ('progress', models.TextField(blank=True, default='')),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('error_message', models.CharField(blank=True, default='', max_length=255)),
                ('result', models.JSONField(default=dict)),
                ('queued_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('lease_expires_at', models.DateTimeField(blank=True, null=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translation_tasks', to='api.chatgptsubscriptionconnection')),
                ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_translation_tasks', to='api.news')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_translation_tasks', to='auth.user')),
            ],
            options={
                'verbose_name': 'ChatGPT 全文翻译任务',
                'verbose_name_plural': 'ChatGPT 全文翻译任务',
                'constraints': [
                    models.UniqueConstraint(fields=('user', 'connection', 'news', 'source_hash'), name='unique_chatgpt_translation_task_source'),
                    models.CheckConstraint(condition=models.Q(('shared_lease_task_id__isnull', True), ('shared_lease_token__isnull', True)) | models.Q(('shared_lease_task_id__isnull', False), ('shared_lease_token__isnull', False)), name='chatgpt_translation_task_shared_lease_pair'),
                ],
            },
        ),
    ]
