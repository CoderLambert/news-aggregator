"""Persist the frozen personal model/credential identity for T09 research runs."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0066_byok_translation_lifecycle')]

    operations = [
        migrations.AddField(
            model_name='researchrun',
            name='execution_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
