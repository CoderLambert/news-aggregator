from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0080_ai_connection_auth_mode')]
    operations = [migrations.AlterField(
        model_name='aimodelprobeattempt', name='proxy_alias', field=models.CharField(max_length=256),
    ), migrations.AddField(
        model_name='aicallattempt', name='route_metadata', field=models.JSONField(default=dict),
    )]
