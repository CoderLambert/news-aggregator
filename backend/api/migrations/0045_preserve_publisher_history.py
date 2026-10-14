from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('api', '0044_article_body_access')]

    operations = [
        migrations.AlterField(
            model_name='news', name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='api.source', verbose_name='来源'),
        ),
        migrations.AlterField(
            model_name='news', name='category',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='api.category', verbose_name='分类'),
        ),
        migrations.AlterField(
            model_name='channelsubscription', name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='channel_subscriptions', to='api.source'),
        ),
    ]
