from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_search_index_control'),
    ]

    operations = [
        migrations.AddField(
            model_name='searchindexrun',
            name='worker_instance_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
