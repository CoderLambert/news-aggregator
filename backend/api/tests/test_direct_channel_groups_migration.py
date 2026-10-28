"""The direct-group schema migration must not reinterpret historical names/data."""
import os
from pathlib import Path
import subprocess
import sys


def test_nullable_parent_migration_preserves_every_existing_parent_and_membership(tmp_path):
    script = r'''
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

old = [('api', '0087_chatgpt_subscription_capability_receipt')]
new = [('api', '0088_direct_channel_groups')]
executor = MigrationExecutor(connection)
executor.migrate(old)
apps = executor.loader.project_state(old).apps
User = apps.get_model('auth', 'User')
Root = apps.get_model('api', 'ChannelGroupRoot')
Group = apps.get_model('api', 'ChannelGroup')
Subscription = apps.get_model('api', 'ChannelSubscription')
Member = apps.get_model('api', 'ChannelGroupMember')
Preference = apps.get_model('api', 'NewsPreference')
Source = apps.get_model('api', 'Source')
a = User.objects.create(username='direct-migration-a')
b = User.objects.create(username='direct-migration-b')
source = Source.objects.create(name='Synthetic migration source', url='https://example.test/direct-migration')
subscription = Subscription.objects.create(user_id=a.pk, source_id=source.pk)
first_root = Root.objects.create(user_id=a.pk, name='OPML 导入')
second_root = Root.objects.create(user_id=b.pk, name='真实父分类')
first = Group.objects.create(user_id=a.pk, root_id=first_root.pk, name='🌐 科技媒体', version=7)
second = Group.objects.create(user_id=b.pk, root_id=second_root.pk, name='🎨 前端 & 设计', version=3)
member = Member.objects.create(group_id=first.pk, subscription_id=subscription.pk)
pref = Preference.objects.create(user_id=a.pk, scope='group', group_id=first.pk)
before = list(Group.objects.order_by('pk').values_list('pk', 'user_id', 'root_id', 'name', 'version'))
root_before = list(Root.objects.order_by('pk').values_list('pk', 'user_id', 'name', 'version'))
executor = MigrationExecutor(connection)
executor.migrate(new)
apps = executor.loader.project_state(new).apps
Group = apps.get_model('api', 'ChannelGroup')
assert list(Group.objects.order_by('pk').values_list('pk', 'user_id', 'root_id', 'name', 'version')) == before
assert list(apps.get_model('api', 'ChannelGroupRoot').objects.order_by('pk').values_list('pk', 'user_id', 'name', 'version')) == root_before
assert apps.get_model('api', 'ChannelGroupMember').objects.filter(pk=member.pk, group_id=first.pk, subscription_id=subscription.pk).exists()
assert apps.get_model('api', 'NewsPreference').objects.get(pk=pref.pk).group_id == first.pk
flat = Group.objects.create(user_id=a.pk, name='直接分组', root_id=None)
assert flat.root_id is None and Group.objects.get(pk=first.pk).root_id == first_root.pk
assert apps.get_model('api', 'ChannelGroupRoot').objects.count() == len(root_before)
connection.close()
'''
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
                   'DJANGO_DB_PATH': str(tmp_path / 'direct-groups-migration.sqlite3'), 'RUN_MAIN': 'true'}
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, '-c', script], cwd=root, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
