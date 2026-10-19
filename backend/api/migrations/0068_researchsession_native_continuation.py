from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0067_researchrun_execution_snapshot')]
    operations = [migrations.AddField(
        model_name='researchsession', name='native_continuation',
        field=models.JSONField(default=dict, blank=True),
    )]
