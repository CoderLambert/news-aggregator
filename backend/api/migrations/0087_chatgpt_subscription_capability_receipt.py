from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [('api', '0086_ai_task_preference_source')]

    operations = [
        migrations.CreateModel(
            name='ChatGPTSubscriptionCapabilityReceipt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('model_slug', models.CharField(max_length=255)),
                ('connection_generation', models.PositiveIntegerField()),
                ('credential_generation', models.PositiveIntegerField()),
                ('capability', models.CharField(default='tools', max_length=32)),
                ('status', models.CharField(choices=[('supported', '支持'), ('unsupported', '不支持'), ('unknown', '未知')], max_length=16)),
                ('safe_error_code', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='capability_receipts', to='api.chatgptsubscriptionconnection')),
            ],
            options={
                'indexes': [models.Index(fields=['connection', 'model_slug', '-created_at'], name='chatgpt_cap_model_created')],
                'constraints': [models.CheckConstraint(condition=models.Q(('capability', 'tools')), name='chatgpt_capability_tools_only')],
            },
        ),
    ]
