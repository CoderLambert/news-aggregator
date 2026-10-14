from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0046_shared_translation_owner'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name='channelintakerequest', name='review_reason',
            field=models.CharField(blank=True, default='', max_length=500)),
        migrations.AddField(model_name='channelintakerequest', name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='channelintakerequest', name='reviewed_by',
            field=models.ForeignKey(blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_channel_intakes', to=settings.AUTH_USER_MODEL)),
    ]
