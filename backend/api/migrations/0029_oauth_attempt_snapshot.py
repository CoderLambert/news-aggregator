from django.db import migrations, models


def fail_legacy_pending_attempts(apps, schema_editor):
    Attempt = apps.get_model('api', 'ChatGPTAuthAttempt')
    Attempt.objects.filter(status__in=['pending', 'authorizing', 'processing']).update(
        status='failed', status_message='config_changed',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0028_account_security'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='auth_mode',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='protocol_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='config_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.RunPython(fail_legacy_pending_attempts, migrations.RunPython.noop),
    ]
