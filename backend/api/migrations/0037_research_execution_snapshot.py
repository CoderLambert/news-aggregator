from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0036_user_ai_task_preferences'),
    ]

    operations = [
        migrations.AddField(
            model_name='researchrun',
            name='execution_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
