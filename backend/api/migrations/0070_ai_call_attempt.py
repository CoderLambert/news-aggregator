import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('api', '0069_private_suggested_questions'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='AICallAttempt',
        fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('task_kind', models.CharField(max_length=32)),
            ('model_config_id', models.UUIDField()),
            ('model_id', models.CharField(max_length=160)),
            ('provider_id', models.CharField(max_length=48)),
            ('status', models.CharField(default='started', max_length=16)),
            ('input_tokens', models.PositiveBigIntegerField(blank=True, null=True)),
            ('output_tokens', models.PositiveBigIntegerField(blank=True, null=True)),
            ('latency_ms', models.PositiveIntegerField(blank=True, null=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('completed_at', models.DateTimeField(blank=True, null=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ],
        options={'ordering': ['-created_at', 'id'], 'indexes': [models.Index(fields=['user', 'created_at'], name='ai_call_owner_created')]},
    )]
