import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0027_chat_ownership'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthSecurityLock',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('revision', models.PositiveBigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='AuthRateBucket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64)),
                ('kind', models.CharField(max_length=32)),
                ('window_start', models.DateTimeField()),
                ('count', models.PositiveIntegerField(default=0)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('key', 'window_start'), name='unique_auth_rate_key_window'),
                ],
            },
        ),
        migrations.CreateModel(
            name='SignupInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_digest', models.CharField(max_length=64, unique=True)),
                ('email', models.EmailField(max_length=254)),
                ('expires_at', models.DateTimeField()),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('consumed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consumed_signup_invites', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
