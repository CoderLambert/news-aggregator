"""Add the original T01 connection model without touching legacy key rows."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0059_bind_retained_legacy_translations'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name='UserAIConnection',
        fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('provider_id', models.CharField(max_length=32)),
            ('endpoint_profile', models.CharField(max_length=48)),
            ('endpoint_profile_version', models.PositiveSmallIntegerField(default=1)),
            ('display_name', models.CharField(max_length=64)),
            ('credential_ciphertext', models.TextField(blank=True, default='')),
            ('encryption_key_id', models.CharField(blank=True, default='', max_length=64)),
            ('credential_epoch', models.PositiveBigIntegerField(default=1)),
            ('credential_version', models.PositiveBigIntegerField(default=1)),
            ('revision', models.PositiveBigIntegerField(default=1)),
            ('request_id', models.UUIDField(default=uuid.uuid4, editable=False)),
            ('request_hash', models.CharField(editable=False, max_length=64)),
            ('is_enabled', models.BooleanField(default=True)),
            ('is_deleted', models.BooleanField(default=False)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('deleted_at', models.DateTimeField(blank=True, null=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name='ai_connections', to=settings.AUTH_USER_MODEL)),
        ],
        options={'ordering': ['-updated_at', 'id'],
            'indexes': [models.Index(fields=['user', 'is_deleted'], name='user_ai_conn_owner_deleted')],
            'constraints': [models.UniqueConstraint(fields=('user', 'request_id'), name='user_ai_conn_request_unique')]},
    )]
