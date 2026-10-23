import os
import subprocess
import sys
from pathlib import Path


def test_forward_migration_preserves_children_and_cancels_only_active_group_work(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = r'''
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

old = [('api', '0084_personal_channel_organization')]
new = [('api', '0085_channel_group_hierarchy')]
executor = MigrationExecutor(connection)
executor.migrate(old)
apps = executor.loader.project_state(old).apps
User = apps.get_model('auth', 'User')
Source = apps.get_model('api', 'Source')
Subscription = apps.get_model('api', 'ChannelSubscription')
Group = apps.get_model('api', 'ChannelGroup')
Member = apps.get_model('api', 'ChannelGroupMember')
Preference = apps.get_model('api', 'NewsPreference')
Config = apps.get_model('api', 'ChannelGroupingConfig')
Override = apps.get_model('api', 'ChannelGroupingOverride')
Proposal = apps.get_model('api', 'ChannelGroupingProposal')

first = User.objects.create(username='hierarchy-first')
second = User.objects.create(username='hierarchy-second')
empty = User.objects.create(username='hierarchy-empty')
source = Source.objects.create(name='Hierarchy source', url='https://example.test/hierarchy')
subscription = Subscription.objects.create(user_id=first.pk, source_id=source.pk)
first_group = Group.objects.create(user_id=first.pk, name='First child')
second_group = Group.objects.create(user_id=second.pk, name='Second child')
member = Member.objects.create(group_id=first_group.pk, subscription_id=subscription.pk)
preference = Preference.objects.create(user_id=first.pk, scope='group', group_id=first_group.pk)
config = Config.objects.create(user_id=first.pk, bindings={'frontend': first_group.pk}, revision=9)
override = Override.objects.create(user_id=first.pk, source_id=source.pk, group_id=first_group.pk, suppressed=True)

common = dict(user_id=first.pk, source_ids=[source.pk], topic_keys=[], input_snapshot='snapshot', expires_at=timezone.now())
active = Proposal.objects.create(target='groups', status='running', dispatch_started_at=timezone.now(), lease_token='lease', lease_until=timezone.now(), **common)
ready = Proposal.objects.create(target='groups', status='ready', **common)
applied = Proposal.objects.create(
    target='groups', status='applied',
    result=[{'source_id': source.pk, 'group_ids': [first_group.pk]}],
    applied_changes=[{'group_id': first_group.pk, 'source_id': source.pk}],
    **common,
)
undone = Proposal.objects.create(target='groups', status='undone', **common)
topic = Proposal.objects.create(target='topics', status='running', lease_token='topic-lease', lease_until=timezone.now(), **common)
active_dispatch = active.dispatch_started_at

executor = MigrationExecutor(connection)
executor.migrate(new)
apps = executor.loader.project_state(new).apps
Group = apps.get_model('api', 'ChannelGroup')
Root = apps.get_model('api', 'ChannelGroupRoot')
Proposal = apps.get_model('api', 'ChannelGroupingProposal')

assert list(Root.objects.order_by('user_id').values_list('user_id', 'name')) == [
    (first.pk, '已有分组'), (second.pk, '已有分组')
]
assert not Root.objects.filter(user_id=empty.pk).exists()
assert Group.objects.get(pk=first_group.pk).root.user_id == first.pk
assert Group.objects.get(pk=second_group.pk).root.user_id == second.pk
assert Group.objects.get(pk=first_group.pk).version == 1
assert apps.get_model('api', 'ChannelGroupMember').objects.filter(pk=member.pk, group_id=first_group.pk, subscription_id=subscription.pk).exists()
assert apps.get_model('api', 'NewsPreference').objects.get(pk=preference.pk).group_id == first_group.pk
assert apps.get_model('api', 'ChannelGroupingConfig').objects.get(pk=config.pk).bindings == {'frontend': first_group.pk}
assert apps.get_model('api', 'ChannelGroupingOverride').objects.filter(pk=override.pk, group_id=first_group.pk).exists()

migrated_active = Proposal.objects.get(pk=active.pk)
assert migrated_active.status == 'failed' and migrated_active.error_code == 'configuration_changed'
assert migrated_active.lease_token == '' and migrated_active.lease_until is None
assert migrated_active.dispatch_started_at == active_dispatch
assert Proposal.objects.get(pk=ready.pk).status == 'failed'
migrated_applied = Proposal.objects.get(pk=applied.pk)
assert migrated_applied.status == 'applied'
assert migrated_applied.result == [{'source_id': source.pk, 'group_ids': [first_group.pk]}]
assert migrated_applied.applied_changes == [{'group_id': first_group.pk, 'source_id': source.pk}]
assert Proposal.objects.get(pk=undone.pk).status == 'undone'
migrated_topic = Proposal.objects.get(pk=topic.pk)
assert migrated_topic.status == 'running' and migrated_topic.lease_token == 'topic-lease'
connection.close()
'''
    environment = {
        **os.environ,
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_DB_PATH': str(tmp_path / 'hierarchy-migration.sqlite3'),
        'RUN_MAIN': 'true',
    }
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=root, env=environment,
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
