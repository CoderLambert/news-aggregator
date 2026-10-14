import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0047_channel_intake_review')]
    operations = [
        migrations.CreateModel(name='MetadataCorrectionAudit', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('run_id', models.UUIDField(db_index=True, default=uuid.uuid4)),
            ('entity', models.CharField(max_length=24)),
            ('object_pk', models.PositiveBigIntegerField()),
            ('source_key', models.CharField(max_length=80)),
            ('input_hash', models.CharField(max_length=64)),
            ('before', models.JSONField()), ('after', models.JSONField()),
            ('operator', models.CharField(max_length=80)),
            ('applied_at', models.DateTimeField(auto_now_add=True)),
            ('undone_at', models.DateTimeField(blank=True, null=True)),
        ], options={'constraints': [models.UniqueConstraint(fields=('run_id', 'entity', 'object_pk'), name='unique_metadata_correction')]}),
        migrations.AlterField(model_name='source', name='country',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='国家')),
    ]
