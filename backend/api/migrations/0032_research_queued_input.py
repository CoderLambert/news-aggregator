from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0031_research_run_recovery'),
    ]

    operations = [
        migrations.AddField(
            model_name='researchrun',
            name='queued_query',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='researchrun',
            name='queued_local_only',
            field=models.BooleanField(default=False),
        ),
    ]
