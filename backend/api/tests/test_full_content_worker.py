from datetime import timedelta
from unittest.mock import Mock, patch
import threading

import pytest
from django.utils import timezone
from django.core.exceptions import ImproperlyConfigured

from api.models import Category, News, Source, RequestBudget
from api.services.full_content_worker import FairQueue, execute_one
from api.services.article_fetcher.types import FetchResult, FullContentCandidate
from api.services.article_fetcher.execution import ExecutionStopped
from api.services.full_content_status import recover_stale_fetches
from newsaggregator.runtime_config import parse_runtime_config


@pytest.fixture
def make_news(db):
    category=Category.objects.create(name='科技',slug='worker')
    sources={key: Source.objects.create(name=name) for key,name in [('webkit','WebKit'),('devto','Dev.to'),('leiphone','雷峰网')]}
    def create(key='webkit', **extra):
        identity=News.objects.count()+1
        root={'webkit':'https://webkit.org/blog/', 'devto':'https://dev.to/person/', 'leiphone':'https://www.leiphone.com/category/ai/'}[key]
        values=dict(title=f'Article {identity}', url=root+f'article-{identity}', publish_time=timezone.now(),
            source=sources[key], category=category, content_kind='article', full_content_fetch_status='queued',
            full_content_next_attempt_at=timezone.now())
        values.update(extra)
        return News.objects.create(**values)
    return create


def test_defaults_separate_execution_automatic_and_structured_admission():
    config=parse_runtime_config({})
    assert not config.structured_body_ingest_enabled and not config.full_content_worker_enabled and not config.full_content_auto_enqueue_enabled
    assert config.structured_body_source_keys == config.full_content_auto_source_keys == frozenset()
    enabled=parse_runtime_config({'FULL_CONTENT_WORKER_ENABLED':'1','STRUCTURED_BODY_SOURCE_KEYS':'devto,svelte_blog'})
    assert enabled.full_content_worker_enabled and not enabled.full_content_auto_enqueue_enabled
    assert enabled.structured_body_source_keys == {'devto','svelte_blog'}


@pytest.mark.parametrize('env', [{'FULL_CONTENT_WORKER_ENABLED':'true'}, {'STRUCTURED_BODY_SOURCE_KEYS':'unknown'}, {'FULL_CONTENT_AUTO_SOURCE_KEYS':'reuters'}, {'STRUCTURED_BODY_SOURCE_KEYS':'leiphone'}, {'FULL_CONTENT_AUTO_SOURCE_KEYS':'meta_ai'}])
def test_unknown_source_or_nonboolean_configuration_is_rejected(env):
    with pytest.raises(ImproperlyConfigured): parse_runtime_config(env)


def test_due_queue_never_scans_unscheduled_history_or_future_or_exhausted(make_news):
    ready=make_news()
    make_news(full_content_fetch_status='pending', full_content_next_attempt_at=None)
    make_news(full_content_next_attempt_at=timezone.now()+timedelta(hours=1), full_content_fetch_status='rate_limited')
    make_news(full_content_retry_count=5)
    assert [news.pk for news in FairQueue().due()] == [ready.pk]


def test_due_queue_rotates_sources_and_priorities_without_starving_other_feeds(make_news):
    low=make_news(full_content_priority=0)
    high=make_news(full_content_priority=10)
    other=make_news('devto')
    third=make_news('leiphone')
    for _ in range(12): make_news(full_content_priority=5)
    queue=FairQueue()
    first=queue.due(2)
    assert [row.pk for row in first] == [high.pk,other.pk]
    assert queue.due(1)[0].pk == third.pk
    assert len(queue.due(999)) == 10


def test_recovery_uses_five_minutes_and_includes_missing_timestamp_without_resetting_failures(make_news):
    stale=make_news(full_content_fetch_status='fetching',last_full_content_attempt=timezone.now()-timedelta(minutes=6),full_content_retry_count=2)
    missing=make_news(full_content_fetch_status='fetching',last_full_content_attempt=None)
    active=make_news(full_content_fetch_status='fetching',last_full_content_attempt=timezone.now()-timedelta(minutes=4))
    assert recover_stale_fetches() == 2
    stale.refresh_from_db(); missing.refresh_from_db(); active.refresh_from_db()
    assert stale.full_content_fetch_status == missing.full_content_fetch_status == 'queued'
    assert stale.full_content_retry_count == 2 and active.full_content_fetch_status == 'fetching'


def test_recovery_preserves_cooldown_recorded_before_process_died(make_news):
    future=timezone.now()+timedelta(hours=1)
    news=make_news(full_content_fetch_status='fetching',last_full_content_attempt=None)
    RequestBudget.objects.create(key='host:webkit.org',cooldown_until=future)
    assert recover_stale_fetches() == 1
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'queued' and news.full_content_next_attempt_at >= future


def test_cancellation_requeues_own_intent_not_before_persistent_host_cooldown(make_news):
    news=make_news(full_content_priority=7,full_content_retry_count=2)
    future=timezone.now()+timedelta(hours=1)
    RequestBudget.objects.create(key='host:webkit.org',cooldown_until=future)
    stop=threading.Event()
    def guard():
        if stop.is_set(): raise ExecutionStopped('canceled')
    class Provider:
        name='synthetic'
        def fetch(self,*args,**kwargs):
            stop.set()
            raise ExecutionStopped('canceled')
    assert execute_one(news,guard=guard,providers=[Provider()]) is None
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'queued' and news.full_content_next_attempt_at >= future
    assert news.full_content_priority == 7 and news.full_content_retry_count == 2


def test_worker_commits_typed_result_and_keeps_existing_body_after_later_failure(make_news):
    news=make_news()
    class Provider:
        name='synthetic'
        def fetch(self,url,**kwargs):
            candidate=FullContentCandidate('webkit',url,url,'https://webkit.org/feed/',None,news.title,'article',
                'content:encoded','html','full','<p>Complete short body.</p>',None,None,timezone.now())
            return FetchResult(True,self.name,url=url,title=news.title,candidate=candidate)
    assert execute_one(news,providers=[Provider()])
    news.refresh_from_db()
    assert news.full_content_state == 'complete' and news.full_content_revision == 1
    from api.services.full_content_status import enqueue_fetch,has_full_content
    enqueue_fetch(news,force=True)
    with patch('api.services.article_fetcher.fetch_article_markdown',side_effect=TimeoutError('controlled timeout')):
        assert execute_one(news) is None
    news.refresh_from_db()
    assert has_full_content(news) and news.full_content == 'Complete short body.'
    assert news.full_content_revision == 1 and news.full_content_retry_count == 1


def test_worker_terminates_unsupported_due_task_without_consuming_network(make_news):
    news=make_news(url='https://www.reuters.com/world/real-story/')
    with patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        execute_one(news)
    fetch.assert_not_called()
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'unsupported' and news.full_content_next_attempt_at is None
