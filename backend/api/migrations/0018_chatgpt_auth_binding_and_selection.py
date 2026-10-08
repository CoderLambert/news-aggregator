import hashlib

import django.db.models.deletion
from django.db import migrations, models


def retire_legacy_subscription_credentials(apps, schema_editor):
    """Keep legacy rows identifiable while requiring a fresh secure login."""
    OAuthClient = apps.get_model('api', 'ChatGPTOAuthClient')
    Connection = apps.get_model('api', 'ChatGPTSubscriptionConnection')
    AuthAttempt = apps.get_model('api', 'ChatGPTAuthAttempt')

    installation = OAuthClient.objects.order_by('pk').first()
    legacy_client_id = installation.issued_client_id if installation else ''
    for connection in Connection.objects.all().iterator():
        connection.issuer = 'legacy'
        connection.issued_client_id = legacy_client_id or 'legacy'
        connection.registration_key_hash = hashlib.sha256(
            f'legacy\0{connection.pk}'.encode('utf-8'),
        ).hexdigest()
        connection.encrypted_subject = ''
        connection.granted_scopes = []
        connection.encrypted_access_token = ''
        connection.encrypted_refresh_token = ''
        connection.access_token_expires_at = None
        connection.is_active = False
        connection.needs_reauth = True
        connection.save(update_fields=[
            'issuer', 'issued_client_id', 'registration_key_hash',
            'encrypted_subject', 'granted_scopes', 'encrypted_access_token',
            'encrypted_refresh_token', 'access_token_expires_at', 'is_active',
            'needs_reauth',
        ])

    AuthAttempt.objects.all().update(
        encrypted_authorization_url='',
        handoff_token_hash='',
        browser_binding_hash='',
        session_binding_hash='',
        status='cancelled',
        status_message='升级后请重新开始授权。',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0017_chatgpt_subscription'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='chatgptsubscriptionconnection',
            name='unique_chatgpt_user_subject',
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='issuer',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='issued_client_id',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='registration_key_hash',
            field=models.CharField(default='', max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='encrypted_subject',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='granted_scopes',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='credential_generation',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='auth_attempt_generation',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='refresh_lease_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='refresh_lease_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='encrypted_authorization_url',
            field=models.TextField(default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='handoff_token_hash',
            field=models.CharField(default='', max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='browser_binding_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='session_binding_hash',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='handoff_origin',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='selection_connection_id_at_start',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='selection_generation_at_start',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='target_attempt_generation',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='status',
            field=models.CharField(db_index=True, default='pending', max_length=16),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='status_message',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='result_connection',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='completed_auth_attempts',
                to='api.chatgptsubscriptionconnection',
            ),
        ),
        migrations.RunPython(
            retire_legacy_subscription_credentials,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='chatgptoauthclient',
            name='issued_client_id',
        ),
        migrations.AddConstraint(
            model_name='chatgptsubscriptionconnection',
            constraint=models.UniqueConstraint(
                fields=('user', 'registration_key_hash'),
                name='unique_chatgpt_user_registration',
            ),
        ),
    ]
