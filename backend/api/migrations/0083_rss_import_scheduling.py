from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('api', '0082_opml_history')]
    operations = [
        migrations.AddField(model_name='feedoperation', name='shared_operation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='subscription_waiters', to='api.feedoperation')),
        migrations.AddField(model_name='rssimportbatch', name='paused', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='rssimportbatch', name='cancelled_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='rssimportitem', name='outcome', field=models.CharField(blank=True, default='', max_length=32)),
        migrations.AddField(model_name='rssimportitem', name='duplicate_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='rssimportitem', name='next_attempt', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddIndex(model_name='rssimportitem', index=models.Index(fields=['status', 'next_attempt'], name='rss_import_due_idx')),
    ]
