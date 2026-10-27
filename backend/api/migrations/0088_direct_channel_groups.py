import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0087_chatgpt_subscription_capability_receipt')]

    operations = [
        migrations.AlterField(
            model_name='channelgroup',
            name='root',
            field=models.ForeignKey(
                to='api.channelgrouproot', null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT, related_name='children',
            ),
        ),
    ]
