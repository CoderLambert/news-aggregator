from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0024_chatgpt_deployment_oauth_host'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='encrypted_id_token',
            field=models.TextField(blank=True, default=''),
        ),
    ]
