from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0026_shared_article_translations'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='oauth_mode',
            field=models.CharField(db_index=True, default='local', max_length=16),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='oauth_mode',
            field=models.CharField(default='local', max_length=16),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='redirect_uri',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='token_auth_method',
            field=models.CharField(default='none', max_length=32),
        ),
    ]
