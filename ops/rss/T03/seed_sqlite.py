"""Synthetic full-schema T03 records, executed only against a new temporary DB."""
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from api.models import Category, ChannelGroup, ChannelGroupMember, ChannelSubscription, Favorite, News, Source
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, FeedSyncState, LegacyTranslationSnapshot, SourceFeedLink, SourcePublication
from api.rss.reading_models import NewsReadState

parameters = json.load(sys.stdin)
assert not Path(os.environ['DJANGO_DB_PATH']).exists(), 'refuse existing database'
call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
actor = get_user_model().objects.create_user('synthetic-rss-t03')
source = Source.objects.create(name='synthetic-rss-t03', url='http://fixture:8000')
category = Category.objects.create(name='Synthetic', slug='synthetic')
binding = FeedBinding.objects.create(engine_instance_uuid=parameters['instance_uuid'], account_id=parameters['account_id'],
    engine_feed_id=parameters['feed_id'], canonical_feed_url='http://fixture:8000/feed', desired_enabled=False)
SourcePublication.objects.create(source=source, owner='paused', reading_policy='standard')
SourceFeedLink.objects.create(source=source, binding=binding, enabled=False)
news = News.objects.create(title='Preserved title', content='Preserved summary', source=source, category=category,
    url=parameters['entry_url'], publish_time=timezone.now(), full_content='Preserved available markdown',
    full_content_zh='保留旧中文正文', body_owner_binding=binding, body_owner_version=3)
mapping = EngineEntryMap.objects.create(binding=binding, engine_entry_id=parameters['entry_id'], news=news,
    source_url=news.url, disposition='linked')
subscription = ChannelSubscription.objects.create(user=actor, source=source)
group = ChannelGroup.objects.create(user=actor, name='Preserved group')
ChannelGroupMember.objects.create(group=group, subscription=subscription)
Favorite.objects.create(user=actor, news=news, type='bookmark')
NewsReadState.objects.create(user=actor, news=news, is_read=True, version=2)
LegacyTranslationSnapshot.objects.create(news=news, field='full_content', source_hash='a'*64,
    translation_hash='b'*64, source_text='old source', translated_text='保留归档译文', origin='legacy')
FeedSyncState.objects.create(engine_instance_uuid=parameters['instance_uuid'], account_id=parameters['account_id'], new_cursor=parameters['entry_id'])
FeedOperation.objects.create(kind='register', actor=actor, binding=binding, dedupe_key='preserved-idempotency',
    request_hash='c'*64, intent_version=1, state='succeeded', safe_input={}, safe_result={'connected': True})
with connection.cursor() as cursor:
    cursor.execute('SELECT app,name FROM django_migrations ORDER BY app,name')
    migrations = [{'app': app, 'name': name} for app, name in cursor.fetchall()]
print(json.dumps({'migrations': migrations, 'news_id': news.pk, 'user_id': actor.pk,
    'binding_id': str(binding.pk), 'mapping_id': str(mapping.pk), 'operation_count': FeedOperation.objects.count()}))
