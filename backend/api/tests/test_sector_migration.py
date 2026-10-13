import os
from pathlib import Path
import subprocess
import sys


def test_sector_migration_preserves_account_configuration_and_existing_articles(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = '''
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
old=[('api','0040_initialize_channel_catalog')]
new=[('api','0042_sector_channels')]
e=MigrationExecutor(connection); e.migrate(old)
a=e.loader.project_state(old).apps
Source=a.get_model('api','Source')
source=Source.objects.get(name='OpenAI Blog')
source.country='CN';source.save()
legacy=Source.objects.create(name='量子位',url='https://www.leiphone.com')
u=a.get_model('auth','User').objects.create(username='existing-reader')
c=a.get_model('api','Category').objects.create(name='Historic',slug='historic')
n=a.get_model('api','News').objects.create(source=source,category=c,title='Stored news',content='Stored summary',url='https://example.test/article',publish_time=timezone.now())
s=a.get_model('api','ChannelSubscription').objects.create(user=u,source=source)
g=a.get_model('api','ChannelGroup').objects.create(user=u,name='Saved group')
a.get_model('api','ChannelGroupMember').objects.create(group=g,subscription=s)
a.get_model('api','NewsPreference').objects.create(user=u,scope='group',group=g)
e=MigrationExecutor(connection);e.migrate(new);a=e.loader.project_state(new).apps
Source=a.get_model('api','Source')
assert Source.objects.get(pk=source.pk).region=='international'
assert Source.objects.get(pk=source.pk).country=='CN'
assert Source.objects.get(pk=legacy.pk).region=='domestic'
assert Source.objects.get(pk=legacy.pk).name=='量子位'
assert Source.objects.get(name='PV Magazine 中文版').region=='domestic'
assert Source.objects.get(name='BBC Health').region=='international'
assert Source.objects.get(name='FDA 新闻稿')
assert a.get_model('api','Category').objects.filter(name__in=['新能源','医疗健康']).count()==2
assert a.get_model('api','News').objects.get(pk=n.pk).content=='Stored summary'
assert a.get_model('api','ChannelSubscription').objects.count()==1
assert a.get_model('api','ChannelGroupMember').objects.count()==1
assert a.get_model('api','NewsPreference').objects.get(user_id=u.pk).group_id==g.pk
'''
    env={**os.environ,'DJANGO_SETTINGS_MODULE':'newsaggregator.settings','DJANGO_ENV':'development','RUN_MAIN':'true',
        'DJANGO_DB_PATH':str(tmp_path/'migration.sqlite3'),'PYTHONPATH':str(root/'backend')}
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
