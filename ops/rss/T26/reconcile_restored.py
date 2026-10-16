"""Real restored-engine reconciliation inside the candidate full app image."""
import json
import os
import time
os.environ.setdefault('DJANGO_SETTINGS_MODULE','newsaggregator.settings')
import django
django.setup()
from api.models import FeedSyncState, News
from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineConfig
from api.rss.reconciliation import SyncWorker
from api.rss.access import get_stored_article
from django.contrib.auth.models import User

config=EngineConfig.from_environment()
control=ControlWorker(config)
worker=SyncWorker(control,config,page_size=1,incremental_seconds=0,reconcile_seconds=0,lookback=0)
before=News.objects.count()
try:
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        worker.tick()
        state=FeedSyncState.objects.filter(engine_instance_uuid=config.engine_instance_uuid,account_id=config.account_id).first()
        if state and state.last_complete_at and state.reconciliation_last_complete_at:
            assert state.new_cursor==4 and News.objects.count()>before
            private=News.objects.get(title='private stored')
            assert get_stored_article(User.objects.get(username='synthetic-a'),private.pk).scope=='full'
            print(json.dumps({'incremental_complete':True,'full_reconciliation_complete':True,'cursor':str(state.new_cursor),
                'before_articles':before,'after_articles':News.objects.count(),'private_paused_preserved':True}))
            break
        time.sleep(.02)
    else:
        raise AssertionError(worker.status())
finally:
    worker.close(); control.close()
