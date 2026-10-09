import hashlib
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def preserve_legacy_deployment_host(apps, schema_editor):
    """Carry the old installation's host into the final deployment model."""
    LegacyClient = apps.get_model('api', 'ChatGPTOAuthClient')
    OAuthHost = apps.get_model('api', 'ChatGPTOAuthHost')
    legacy = LegacyClient.objects.using(schema_editor.connection.alias).order_by('pk').first()
    if legacy is None:
        return

    # Keep migration-time identity initialization self-contained so historical
    # migrations do not import services tied to the current database schema.
    configured = str(getattr(settings, 'CHATGPT_DEPLOYMENT_INSTANCE_ID', '')).strip()
    if configured:
        instance_id = str(uuid.UUID(configured))
    else:
        path = Path(getattr(
            settings, 'CHATGPT_DEPLOYMENT_INSTANCE_FILE',
            Path(settings.BASE_DIR) / '.runtime' / 'chatgpt-deployment-id',
        ))
        try:
            value = path.read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            value = str(uuid.uuid4())
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                value = path.read_text(encoding='utf-8').strip()
            else:
                with os.fdopen(descriptor, 'w', encoding='ascii') as deployment_file:
                    deployment_file.write(f'{value}\n')
        instance_id = str(uuid.UUID(value))

    deployment_hash = hashlib.sha256(instance_id.encode('utf-8')).hexdigest()
    OAuthHost.objects.using(schema_editor.connection.alias).get_or_create(
        deployment_hash=deployment_hash,
        defaults={'host_id': legacy.host_id},
    )


def consolidate_deployment_hosts(apps, schema_editor):
    """Keep one host per deployment, preferring a host with saved credentials."""
    OAuthHost = apps.get_model('api', 'ChatGPTUserOAuthHost')
    Connection = apps.get_model('api', 'ChatGPTSubscriptionConnection')
    AuthAttempt = apps.get_model('api', 'ChatGPTAuthAttempt')

    deployment_hashes = OAuthHost.objects.order_by().values_list(
        'deployment_hash', flat=True,
    ).distinct()
    for deployment_hash in deployment_hashes:
        hosts = list(OAuthHost.objects.filter(
            deployment_hash=deployment_hash,
        ).order_by('created_at', 'pk'))
        if len(hosts) < 2:
            continue

        host_by_user = {host.user_id: host for host in hosts}
        preferred_user_id = Connection.objects.filter(
            user_id__in=host_by_user,
        ).order_by('-is_active', 'created_at').values_list('user_id', flat=True).first()
        keeper = host_by_user.get(preferred_user_id, hosts[0])
        OAuthHost.objects.filter(
            deployment_hash=deployment_hash,
        ).exclude(pk=keeper.pk).delete()

    AuthAttempt.objects.filter(
        status__in=['pending', 'authorizing', 'processing'],
    ).update(
        status='cancelled',
        status_message='OAuth 主机标识已校正，请重新开始登录。',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_chatgpt_user_oauth_hosts'),
    ]

    operations = [
        migrations.RunPython(
            consolidate_deployment_hosts,
            migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name='chatgptuseroauthhost',
            name='unique_chatgpt_user_deployment_host',
        ),
        migrations.RemoveField(
            model_name='chatgptuseroauthhost',
            name='user',
        ),
        migrations.RenameModel(
            old_name='ChatGPTUserOAuthHost',
            new_name='ChatGPTOAuthHost',
        ),
        migrations.AlterField(
            model_name='chatgptoauthhost',
            name='deployment_hash',
            field=models.CharField(max_length=64, unique=True),
        ),
        migrations.AlterModelOptions(
            name='chatgptoauthhost',
            options={
                'verbose_name': 'ChatGPT OAuth 主机',
                'verbose_name_plural': 'ChatGPT OAuth 主机',
            },
        ),
        migrations.RunPython(
            preserve_legacy_deployment_host,
            migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name='ChatGPTOAuthClient',
        ),
    ]
