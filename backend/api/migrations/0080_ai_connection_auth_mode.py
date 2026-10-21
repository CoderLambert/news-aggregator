from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0079_personal_channel_category')]

    operations = [
        migrations.AddField(
            model_name='useraiconnection', name='auth_mode',
            field=models.CharField(choices=[('api_key', 'API Key'), ('none', 'No Key')],
                                   default='api_key', max_length=8),
        ),
        migrations.AddField(
            model_name='useraiconnection', name='endpoint_policy_digest',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
    ]
