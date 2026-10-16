"""Create only synthetic accounts and sources in the explicitly isolated SQLite DB."""
import json
import os
import time
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
assert '/newshub-rss-t27-' in os.environ['DJANGO_DB_PATH']
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from api.models import (Category, SourceConfig, ChannelGroup, ChannelSubscription, News, Source, SourcePublication, SourceFeedLink, FeedBinding, FeedSyncState)
from api.rss.engine import EngineConfig
from api.rss.control_worker import ControlWorker
from api.rss.operations import enqueue_operation
from api.rss.reconciliation import SyncWorker
from api.rss.directory import import_pinned_seed
call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
a = get_user_model().objects.create_user('t27_alice', password='Synthetic-T27-pass-123', is_staff=True, is_superuser=True)
b = get_user_model().objects.create_user('t27_bob', password='Synthetic-T27-pass-123')
groups = [ChannelGroup.objects.create(user=a, name=name) for name in ['T27 Reading', 'T27 Research']]
category, _ = Category.objects.get_or_create(name='T27 Synthetic', defaults={'slug': 't27-synthetic'})
config = EngineConfig.from_environment()
control = ControlWorker(config)
sources = {}
for name, publication, user in [('public', 'public', None), ('private-a', 'personal', a), ('private-b', 'personal', b), ('restricted', 'public', None)]:
    publisher = 'restricted.publisher.example' if name == 'restricted' else 'publisher.example'
    source = Source.objects.create(name='T27 ' + name, url=f'https://{publisher}:8443/')
    SourceConfig.objects.create(source_key='t27_'+name.replace('-', '_'), source=source, publisher_name='Synthetic', channel_name=name, category=category, status='enabled', approved_config_version=1, approved_at=timezone.now(), approved_by=a, feed_full_content_allowed=name!='restricted', official_html_full_content_allowed=name!='restricted', reading_policy='summary_only' if name=='restricted' else 'public_feed')
    SourcePublication.objects.create(source=source, publication=publication, owner='miniflux',
        display_name='T27 ' + name, reading_policy='summary_only' if name == 'restricted' else 'public_feed')
    binding = FeedBinding.objects.create(engine_instance_uuid=config.engine_instance_uuid, account_id=2,
        canonical_feed_url=f'https://{publisher}:8443/feed/' + name, desired_mode='feed', desired_enabled=True)
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True, editorial_pin=user is None)
    for subscriber in ([user] if user else [a, b]):
        ChannelSubscription.objects.create(user=subscriber, source=source)
    enqueue_operation('register', actor=user, binding=binding, dedupe_key='bootstrap-' + name)
    sources[name] = {'id': source.pk, 'binding': str(binding.pk)}
collection_started = time.monotonic()
for _ in range(20):
    if not control.run_once():
        break
sync = SyncWorker(control, config)
end = time.monotonic() + 30
while time.monotonic() < end:
    sync.tick()
    if FeedSyncState.objects.filter(last_complete_at__isnull=False).exists():
        break
    time.sleep(0.02)
assert News.objects.count() == 4, News.objects.count()
for name, data in sources.items():
    news = News.objects.get(source_id=data['id'])
    data['news_id'] = news.pk
    assert news.full_content
sync.close(); control.close()
import_pinned_seed()
print(json.dumps({'sources': sources, 'groups': [group.pk for group in groups], 'users': {'a': a.pk, 'b': b.pk}, 'collection_to_visible_seconds': round(time.monotonic()-collection_started, 3)}))
