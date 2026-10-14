from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0045_preserve_publisher_history'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='sharedarticletranslationtask',
            name='initiated_by',
            field=models.ForeignKey(blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shared_translation_attempts',
                to=settings.AUTH_USER_MODEL),
        ),
    ]
