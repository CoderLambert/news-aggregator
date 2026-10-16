"""Executed in the actual lightweight container against synthetic DB and engine."""
import json
import os
import platform
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from api.models import Category, ChannelSubscription, News, Source
from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineAdapter, EngineConfig
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
from api.rss.operations import change_policy, enqueue_operation, get_operation_for_actor, reconcile_binding, refetch_handoffs

call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
config = EngineConfig.from_environment()
adapter = EngineAdapter(config)
worker = ControlWorker(config)
url = 'https://publisher.example:8443/feed'
actors = [get_user_model().objects.create_user(f'live-user-{i}') for i in range(20)]
source = Source.objects.create(name='rss-live', url='https://publisher.example:8443')
SourcePublication.objects.create(source=source, owner='miniflux', reading_policy='standard')
binding = FeedBinding.objects.create(engine_instance_uuid=config.engine_instance_uuid,
    account_id=config.account_id, canonical_feed_url=url, desired_mode='full_content', desired_enabled=True)
SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
for actor in actors:
    ChannelSubscription.objects.create(user=actor, source=source)
    enqueue_operation('register', actor=actor, binding=binding, dedupe_key='register')


def drain():
    for _ in range(100):
        if not worker.run_once():
            return
    raise AssertionError('unbounded ready operations')


drain()
assert len(adapter.list_feeds()) == 1
assert FeedOperation.objects.filter(kind='register', state='succeeded').count() == 20
binding.refresh_from_db()
refresh = enqueue_operation('refresh_feed', actor=actors[0], binding=binding, dedupe_key='refresh')
drain()
refresh.refresh_from_db()
assert refresh.state == 'succeeded'
ChannelSubscription.objects.filter(source=source).delete()
reconcile_binding(binding.pk)
drain()
assert adapter.get_feed(binding.engine_feed_id).disabled is True
ChannelSubscription.objects.create(user=actors[0], source=source)
reconcile_binding(binding.pk)
drain()
binding.refresh_from_db()
for mode in ('feed', 'full_content'):
    change_policy(binding.pk, expected_policy_version=binding.policy_version, desired_mode=mode)
    drain()
    binding.refresh_from_db()
    assert binding.applied_policy_version == binding.policy_version
    assert adapter.get_feed(binding.engine_feed_id).crawler is (mode == 'full_content')
entries = adapter.list_entries(0, adapter.read_upper_bound())
assert len(entries) == 1
remote = entries[0]
category = Category.objects.create(name='Synthetic', slug='synthetic')
news = News.objects.create(title=remote.title, content='summary', source=source, category=category,
    url=remote.url, publish_time=timezone.now(), full_content='local body remains unchanged',
    body_owner_binding=binding, body_owner_version=1)
entry = EngineEntryMap.objects.create(binding=binding, engine_entry_id=remote.id, news=news, source_url=news.url)
refetch = enqueue_operation('refetch_entry', actor=actors[0], binding=binding, entry=entry,
    source_id=source.pk, dedupe_key='refetch')
drain()
refetch.refresh_from_db(); news.refresh_from_db()
assert refetch.state == 'succeeded' and refetch.safe_result['pending_sync']
assert news.full_content == 'local body remains unchanged' and len(list(refetch_handoffs())) == 1
discoveries = {}
for name, count in [('zero', 0), ('one', 1), ('many', 3)]:
    host = 'zero.publisher.example' if name == 'zero' else 'publisher.example'
    operation = enqueue_operation('discover', actor=actors[0], dedupe_key='discover-' + name,
        url='https://' + host + ':8443/discover-' + name)
    drain()
    view = get_operation_for_actor(actors[0], operation.pk)
    assert view['state'] == 'succeeded', view
    assert len(view['result']['candidates']) == count, view
    discoveries[name] = count
slow = enqueue_operation('discover', actor=actors[0], dedupe_key='discover-slow',
    url='https://publisher.example:8443/slow')
worker.run_once()
slow.refresh_from_db()
assert slow.state != 'succeeded' and len(adapter.list_feeds()) == 1
assert 'api.services.embedding' not in sys.modules and 'scrapy' not in sys.modules
worker.close(); adapter.close()
print(json.dumps({'python': platform.python_version(), 'registered_actor_operations': 20,
    'physical_feeds': 1, 'last_reference_disabled': True, 'policy_verified': True,
    'refetch_pending_fenced_sync': True, 'local_news_unchanged': True,
    'discoveries': discoveries, 'timeout_state': slow.state, 'timeout_code': slow.safe_result['code'],
    'sync_ready': False}, sort_keys=True))
