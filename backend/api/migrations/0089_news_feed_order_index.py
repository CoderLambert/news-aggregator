from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0088_direct_channel_groups')]

    operations = [
        migrations.AddIndex(
            model_name='news',
            index=models.Index(fields=['related_to', '-publish_time'], name='news_feed_order_idx'),
        ),
    ]
