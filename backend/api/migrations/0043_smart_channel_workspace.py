import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('api', '0042_sector_channels'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='SourceTopicProfile', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('about', models.TextField(blank=True, default='')), ('topics', models.JSONField(default=list)),
            ('origin', models.CharField(default='rules', max_length=16)), ('evidence_hash', models.CharField(default='', max_length=64)),
            ('revision', models.PositiveBigIntegerField(default=1)), ('updated_at', models.DateTimeField(auto_now=True)),
            ('source', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='topic_profile', to='api.source')),
        ]),
        migrations.CreateModel(name='ChannelGroupingConfig', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('mode', models.CharField(default='suggest', max_length=16)), ('bindings', models.JSONField(default=dict)),
            ('revision', models.PositiveBigIntegerField(default=1)), ('active_since', models.DateTimeField(default=django.utils.timezone.now)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='channel_grouping_config', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='ChannelGroupingOverride', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('suppressed', models.BooleanField(default=False)), ('touched_at', models.DateTimeField(auto_now=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api.source')),
            ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api.channelgroup')),
        ], options={'constraints': [models.UniqueConstraint(fields=('user', 'source', 'group'), name='unique_grouping_override')]}),
        migrations.CreateModel(name='ChannelGroupingProposal', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('request_id', models.UUIDField(default=uuid.uuid4)), ('engine', models.CharField(default='rules', max_length=16)),
            ('status', models.CharField(db_index=True, default='ready', max_length=16)),
            ('source_ids', models.JSONField(default=list)), ('topic_keys', models.JSONField(default=list)),
            ('input_snapshot', models.CharField(max_length=64)), ('request_hash', models.CharField(default='', max_length=64)),
            ('evidence', models.JSONField(default=list)), ('result', models.JSONField(default=list)),
            ('applied_changes', models.JSONField(default=list)), ('applied_at', models.DateTimeField(blank=True, null=True)),
            ('credential_fingerprint', models.CharField(blank=True, default='', max_length=64)),
            ('model_id', models.CharField(blank=True, default='', max_length=160)), ('attempts', models.PositiveSmallIntegerField(default=0)),
            ('lease_token', models.CharField(blank=True, default='', max_length=64)), ('lease_until', models.DateTimeField(blank=True, null=True)),
            ('next_attempt_at', models.DateTimeField(default=django.utils.timezone.now)), ('error_code', models.CharField(blank=True, default='', max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('expires_at', models.DateTimeField()),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ('public_source', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api.source')),
        ], options={'ordering': ['-created_at'], 'constraints': [models.UniqueConstraint(fields=('user', 'request_id'), name='unique_grouping_request')]}),
        migrations.CreateModel(name='SubscriptionGroupingState', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('status', models.CharField(default='pending', max_length=16)), ('profile_hash', models.CharField(default='', max_length=64)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('subscription', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='api.channelsubscription')),
        ]),
        migrations.CreateModel(name='ChannelClassifierSettings', fields=[
            ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ('enabled', models.BooleanField(default=False)), ('daily_limit', models.PositiveSmallIntegerField(default=10)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='ReadingDay', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('day', models.DateField(db_index=True)), ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api.news')),
        ], options={'constraints': [models.UniqueConstraint(fields=('user', 'news', 'day'), name='unique_reader_news_day')],
                    'indexes': [models.Index(fields=['user', 'day'], name='reader_day_lookup')]}),
        migrations.CreateModel(name='ChannelIntakeRequest', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('url', models.URLField(max_length=1024)), ('status', models.CharField(default='pending', max_length=16)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={'constraints': [models.UniqueConstraint(fields=('user', 'url'), name='unique_channel_intake')]}),
    ]
