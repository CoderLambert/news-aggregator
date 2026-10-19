from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0070_ai_call_attempt')]
    operations = [
        migrations.AddField(model_name='channelgroupingproposal', name='execution_snapshot', field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='channelgroupingproposal', name='dispatch_started_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='channelclassifiersettings', name='execution_snapshot', field=models.JSONField(default=dict, blank=True)),
    ]
