import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def create_legacy_roots(apps, schema_editor):
    ChannelGroup = apps.get_model('api', 'ChannelGroup')
    ChannelGroupRoot = apps.get_model('api', 'ChannelGroupRoot')
    ChannelGroupingProposal = apps.get_model('api', 'ChannelGroupingProposal')

    owner_ids = list(ChannelGroup.objects.order_by().values_list('user_id', flat=True).distinct())
    now = timezone.now()
    for owner_id in owner_ids:
        root = ChannelGroupRoot.objects.create(user_id=owner_id, name='已有分组')
        ChannelGroup.objects.filter(user_id=owner_id, root__isnull=True).update(root_id=root.pk, updated_at=now)

    if ChannelGroup.objects.filter(root__isnull=True).exists():
        raise RuntimeError('channel group hierarchy migration left an unowned child')
    if ChannelGroup.objects.exclude(user_id=models.F('root__user_id')).exists():
        raise RuntimeError('channel group hierarchy migration created a cross-owner child')

    ChannelGroupingProposal.objects.filter(
        target='groups', status__in=['queued', 'running', 'ready'],
    ).update(
        status='failed', error_code='configuration_changed', lease_token='', lease_until=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0084_personal_channel_organization'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChannelGroupRoot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40)),
                ('version', models.PositiveBigIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='channel_group_roots', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'constraints': [models.UniqueConstraint(fields=('user', 'name'), name='unique_user_channel_group_root_name')],
            },
        ),
        migrations.AddField(
            model_name='channelgroup',
            name='root',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='api.channelgrouproot'),
        ),
        migrations.AddField(
            model_name='channelgroup',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='channelgroup',
            name='version',
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.RunPython(create_legacy_roots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='channelgroup',
            name='root',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='children', to='api.channelgrouproot'),
        ),
        migrations.AlterField(
            model_name='channelgroup',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
