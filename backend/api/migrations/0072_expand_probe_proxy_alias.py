from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0071_classification_execution_snapshot')]

    operations = [
        migrations.AlterField(
            model_name='aimodelprobeattempt',
            name='proxy_alias',
            field=models.CharField(max_length=240),
        ),
    ]
