import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import api.models


def cancel_attempts_from_shared_host(apps, schema_editor):
    AuthAttempt = apps.get_model('api', 'ChatGPTAuthAttempt')
    AuthAttempt.objects.filter(
        status__in=['pending', 'authorizing', 'processing'],
    ).update(
        status='cancelled',
        status_message='用户独立授权已启用，请重新开始登录。',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_searchindexrun_worker_instance_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatGPTUserOAuthHost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deployment_hash', models.CharField(max_length=64)),
                ('host_id', models.CharField(default=api.models.generate_chatgpt_host_id, max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_oauth_hosts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'ChatGPT 用户 OAuth 主机',
                'verbose_name_plural': 'ChatGPT 用户 OAuth 主机',
            },
        ),
        migrations.AddConstraint(
            model_name='chatgptuseroauthhost',
            constraint=models.UniqueConstraint(fields=('user', 'deployment_hash'), name='unique_chatgpt_user_deployment_host'),
        ),
        migrations.RunPython(
            cancel_attempts_from_shared_host,
            migrations.RunPython.noop,
        ),
    ]
