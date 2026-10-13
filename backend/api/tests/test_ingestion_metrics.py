"""Offline metrics contracts: validation, persistence and wire IO stay distinct."""
from datetime import timedelta
from dataclasses import replace
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import ArticleFetchEvent, Category, CrawlBatch, CrawlerTarget, CrawlRun, FeedState, News, RequestBudget, Source
from api.services.article_fetch_monitor import monitor_dashboard, record_fetch_event
from api.services.article_fetcher import fetch_article_markdown, safe_http
from api.services.article_fetcher.types import FetchResult, FullContentCandidate, transport_failure
from api.services.crawl_metrics import RESULT_PREFIX, crawl_result
from api.services.full_content_status import enqueue_fetch, mark_success
from api.services.full_content_worker import execute_one
from api.tests.test_safe_http import FakeNetwork, _response

pytestmark = pytest.mark.django_db


@pytest.fixture
def article():
    return News.objects.create(title='Metrics article', content='Short summary.',
        url='https://webkit.org/blog/123/metrics-article/', publish_time=timezone.now(),
        source=Source.objects.update_or_create(name='WebKit', defaults={})[0], category=Category.objects.create(name='Metrics', slug='metrics'),
        content_kind='article', full_content_fetch_status='queued', full_content_next_attempt_at=timezone.now())


class TypedProvider:
    name = 'offline_typed'

    def fetch(self, url, expected_title=None, **kwargs):
        candidate = FullContentCandidate('webkit', url, url, 'https://webkit.org/feed/', None,
            expected_title, 'article', 'content:encoded', 'html', 'full',
            '<p>Complete publisher body for metrics.</p>', None, None, timezone.now())
        return FetchResult(True, self.name, url=url, title=expected_title, candidate=candidate)


def test_validation_without_persistence_is_not_saved_success(article):
    result = fetch_article_markdown(article.url, expected_title=article.title, news=article, providers=[TypedProvider()])
    event = ArticleFetchEvent.objects.get(pk=result.fetch_event_id)
    assert event.outcome == 'validated' and event.persistence_outcome == 'not_attempted'
    assert event.source_key == 'webkit' and event.physical_requests == 0 and event.http_statuses == []
    article.refresh_from_db()
    assert article.full_content == '' and article.full_content_revision == 0
    dashboard = monitor_dashboard()
    assert dashboard['summary']['total'] == 1 and dashboard['summary']['success'] == 0
    assert dashboard['domains'][0]['succeeded'] == 0


def test_worker_counts_commit_once_and_separates_identical_body_noop(article):
    first = execute_one(article, providers=[TypedProvider()])
    first_event = ArticleFetchEvent.objects.get(pk=first.fetch_event_id)
    assert first_event.persistence_outcome == first_event.logical_outcome == 'committed'
    article.refresh_from_db()
    assert article.full_content_state == 'complete' and article.full_content_revision == 1
    enqueue_fetch(article, force=True)
    second = execute_one(article, providers=[TypedProvider()])
    second_event = ArticleFetchEvent.objects.get(pk=second.fetch_event_id)
    assert second_event.outcome == 'validated' and second_event.persistence_outcome == 'noop'
    article.refresh_from_db()
    assert article.full_content_revision == 1
    assert monitor_dashboard()['summary']['success'] == 1


def test_validated_candidate_losing_revision_cas_is_not_committed(article):
    def lose_revision(news, result):
        News.objects.filter(pk=news.pk).update(full_content_revision=1)
        return mark_success(news, result)
    with patch('api.services.full_content_worker.mark_success', side_effect=lose_revision):
        assert execute_one(article, providers=[TypedProvider()]) is None
    event = ArticleFetchEvent.objects.get()
    assert event.outcome == 'validated' and event.persistence_outcome == 'persistence_conflict'
    assert event.logical_outcome == 'persistence_conflict'
    article.refresh_from_db()
    assert article.full_content == ''
    assert monitor_dashboard()['summary']['success'] == 0


def test_legacy_unbound_validation_and_historical_success_are_not_commits(article):
    event_id = record_fetch_event(url=article.url, news_id=article.pk,
        result=FetchResult(True, 'diagnostic', markdown='Unbound diagnostic body.'), failures=[], elapsed_ms=2)
    event = ArticleFetchEvent.objects.get(pk=event_id)
    assert event.outcome == 'legacy_validated' and event.persistence_outcome == 'not_attempted'
    ArticleFetchEvent.objects.create(news=article, domain='webkit.org', outcome='success')
    assert monitor_dashboard()['summary']['success'] == 0


@pytest.mark.parametrize('invalid', [
    {'target_url': 'https://webkit.org/blog/456/other-article/'},
    {'declared_completeness': 'partial'},
    {'body_field': 'description'},
])
def test_wrong_identity_partial_or_summary_candidate_never_increases_saved_success(article, invalid):
    class InvalidProvider(TypedProvider):
        def fetch(self, *args, **kwargs):
            result = super().fetch(*args, **kwargs)
            result.candidate = replace(result.candidate, **invalid)
            return result
    assert execute_one(article, providers=[InvalidProvider()]) is None
    event = ArticleFetchEvent.objects.get()
    assert event.outcome == 'failed' and event.persistence_outcome == 'not_attempted'
    assert monitor_dashboard()['summary']['success'] == 0
    article.refresh_from_db()
    assert article.full_content == '' and article.full_content_revision == 0


class WireProvider:
    name = 'offline_wire'

    def __init__(self, *, raw_errors=False):
        self.raw_errors = raw_errors

    def fetch(self, url, **kwargs):
        try:
            safe_http.safe_urlopen(url)
        except safe_http.SafeHTTPStatusError as error:
            if self.raw_errors:
                raise
            return transport_failure(error, provider=self.name, url=url)
        raise AssertionError('Expected transport control failure')


def test_budget_deferred_has_zero_actual_requests_and_durable_deadline(article, monkeypatch):
    article.url = article.url.replace('https:', 'http:')
    article.save(update_fields=['url'])
    future = timezone.now() + timedelta(minutes=3)
    RequestBudget.objects.create(key='host:webkit.org', cooldown_until=future)
    network = FakeNetwork(monkeypatch, [])
    assert execute_one(article, providers=[WireProvider()]) is None
    event = ArticleFetchEvent.objects.get()
    assert event.outcome == 'failed' and event.logical_outcome == 'budget_deferred'
    assert event.physical_requests == 0 and event.http_statuses == [] and not network.sockets
    assert event.retry_after_at >= future and event.persistence_outcome == 'not_attempted'


def test_redirect_and_429_record_actual_wire_count_and_cooldown(article, monkeypatch):
    from api.services import request_budget
    article.url = article.url.replace('https:', 'http:')
    article.save(update_fields=['url'])
    now = timezone.now()
    monkeypatch.setattr(request_budget.timezone, 'now', lambda: now)
    def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
    monkeypatch.setattr(safe_http.time, 'sleep', advance)
    network = FakeNetwork(monkeypatch, [
        _response(302, 'Location: /blog/123/final/\r\nContent-Length: 0\r\n'),
        _response(429, 'Retry-After: 120\r\nContent-Length: 0\r\n'),
    ])
    assert execute_one(article, providers=[WireProvider()]) is None
    event = ArticleFetchEvent.objects.get()
    assert event.physical_requests == len(network.sockets) == 2
    assert event.http_statuses == [302, 429] and event.logical_outcome == 'rate_limited'
    assert event.retry_after_at >= now + timedelta(seconds=119)
    assert event.persistence_outcome == 'not_attempted'
    article.refresh_from_db()
    assert article.full_content_fetch_status == 'rate_limited' and article.full_content == ''


def test_uncaught_provider_429_still_preserves_control_outcome_and_stops_fallback(article, monkeypatch):
    article.url = article.url.replace('https:', 'http:')
    article.save(update_fields=['url'])
    FakeNetwork(monkeypatch, [_response(429, 'Retry-After: 120\r\nContent-Length: 0\r\n')])
    class NeverFallback:
        name = 'never_after_429'
        def fetch(self, *args, **kwargs):
            raise AssertionError('429 must stop the whole provider chain')
    assert execute_one(article, providers=[WireProvider(raw_errors=True), NeverFallback()]) is None
    event = ArticleFetchEvent.objects.get()
    assert event.logical_outcome == 'rate_limited' and event.physical_requests == 1
    assert event.http_statuses == [429] and event.retry_after_at is not None
    assert len(event.failure_codes) == 1


def test_coverage_excludes_legacy_raw_missing_products_abstracts_and_ineligible(article):
    def add(suffix, **changes):
        values = dict(title=suffix, content='Summary only', content_kind='article',
            url=f'https://webkit.org/blog/123/{suffix}/', publish_time=timezone.now(),
            source=article.source, category=article.category)
        values.update(changes)
        return News.objects.create(**values)
    add('complete', full_content_state='complete', full_content='Committed body')
    add('legacy', full_content_state='legacy', full_content='Historical readable body')
    add('raw-missing', full_content_state='missing', full_content='Unvalidated raw text')
    add('product', content_kind='product', full_content_state='complete', full_content='Product description')
    add('abstract', content_kind='abstract', full_content_state='complete', full_content='Abstract')
    add('ineligible', url='https://www.reuters.com/world/story/', full_content_state='complete', full_content='Body')
    future = timezone.now() + timedelta(minutes=2)
    RequestBudget.objects.create(key='host:webkit.org', cooldown_until=future)
    FeedState.objects.create(source_key='webkit', feed_url='https://webkit.org/feed/', next_poll_at=future)
    ArticleFetchEvent.objects.create(news=article, domain='webkit.org', outcome='validated', persistence_outcome='not_attempted')
    stdout = StringIO()
    call_command('full_content_stats', '--json', stdout=stdout)
    result = json.loads(stdout.getvalue())
    assert result['coverage_denominator'] == 'eligible_article'
    assert result['eligible_articles'] == 4 and result['complete_eligible_articles'] == 1
    assert result['coverage'] == 0.25 and result['legacy_body_count'] == 1
    assert result['content_readiness']['summary_only'] == 2
    assert result['queue']['pending'] == result['queue']['due'] == 1
    assert result['budget']['cooling_scopes'] == 1
    assert result['feeds'][0]['source_key'] == 'webkit'
    assert result['attempts'] == {'not_attempted': 1}


@pytest.mark.parametrize(('stats', 'outcome'), [
    ({'persistence_failures': 1}, 'partial'),
    ({'parse_failures': 1}, 'parse_failed'),
    ({'downloader/response_status_count/429': 1}, 'rate_limited'),
    ({'budget/deferred': 1}, 'deferred'),
    ({'entries_changed': 1, 'entries_committed': 1}, 'updated'),
    ({'entries_seen': 1, 'entries_committed': 1}, 'unchanged'),
    ({'downloader/response_count': 1}, 'valid_empty'),
])
def test_crawl_metrics_distinguish_ingestion_from_process_exit(stats, outcome):
    assert crawl_result({'finish_reason': 'finished', **stats})['outcome'] == outcome


def test_json_crawl_summary_wins_over_legacy_process_success_and_skips_invalid_json(tmp_path):
    from api.management.commands.crawl_worker import parse_summary
    path = tmp_path / 'metrics.log'
    result = {'outcome': 'partial', 'items': 1, 'responses': 1, 'errors': 0, 'persistence_failures': 1}
    path.write_text('爬虫汇总 source=metrics finish=finished items=1 responses=1 errors=0 http=200:1\n'
        + RESULT_PREFIX + json.dumps(result) + '\n'
        + RESULT_PREFIX + json.dumps({'outcome': 'updated', 'items': True, 'responses': 1, 'errors': 0}) + '\n'
        + RESULT_PREFIX + '{broken json}\n')
    assert parse_summary(path) == result


@pytest.mark.parametrize('outcome', ['partial', 'rate_limited', 'parse_failed', 'deferred', 'updated', 'unchanged', 'valid_empty'])
def test_zero_exit_worker_uses_json_result_and_persists_ingestion_counters(tmp_path, outcome):
    from api.management.commands.crawl_worker import Command, parse_summary
    target = CrawlerTarget.objects.create(spider_name='metrics', display_name='Metrics')
    batch = CrawlBatch.objects.create(trigger='manual')
    run = CrawlRun.objects.create(target=target, batch=batch, status='running')
    stats = {'outcome': outcome, 'items': 2, 'responses': 1, 'errors': 0, 'finish_reason': 'finished',
        'entries_seen': 3, 'entries_committed': 2, 'persistence_failures': 1 if outcome == 'partial' else 0,
        'physical_requests': 1, 'http_statuses': {'429': 1} if outcome == 'rate_limited' else {'200': 1},
        'checkpoint_committed': False, 'policy_skips_by_reason': {'too_old': 1}}
    def start_process(*args, **kwargs):
        kwargs['stdout'].write(RESULT_PREFIX + json.dumps(stats) + '\n')
        kwargs['stdout'].flush()
        return SimpleNamespace(poll=lambda: 0, returncode=0)
    command = Command()
    command.stopping = False
    with patch('api.management.commands.crawl_worker.subprocess.Popen', side_effect=start_process):
        command._execute_run(run, 'offline-metrics-worker', tmp_path)
    run.refresh_from_db()
    assert run.exit_code == 0
    assert run.status == ('succeeded' if outcome in {'updated', 'unchanged', 'valid_empty'} else 'failed')
    assert run.stats['outcome'] == outcome and run.stats['entries_committed'] == 2
    assert run.stats['physical_requests'] == 1 and run.stats['checkpoint_committed'] is False
    assert run.http_statuses == stats['http_statuses']
    assert parse_summary(tmp_path / f'{run.id}.log') == stats


@pytest.mark.parametrize(('stats', 'outcome'), [
    ({'outcome': 'updated', 'persistence_failures': 1}, 'partial'),
    ({'outcome': 'unchanged', 'parse_failures': 1}, 'parse_failed'),
    ({'outcome': 'valid_empty', 'downloader/response_status_count/429': 1}, 'rate_limited'),
    ({'outcome': 'updated', 'budget/deferred': 1}, 'deferred'),
])
def test_claimed_success_cannot_hide_known_ingestion_failure(stats, outcome):
    assert crawl_result({'finish_reason': 'finished', **stats})['outcome'] == outcome



def test_force_preserves_failures_cooldown_and_original_task_creation(article):
    initial = timezone.now() - timedelta(hours=2)
    future = timezone.now() + timedelta(hours=1)
    News.objects.filter(pk=article.pk).update(full_content_retry_count=3, full_content_priority=2,
        full_content_task_created_at=initial, full_content_next_attempt_at=future)
    article.refresh_from_db()
    assert enqueue_fetch(article, force=True) == 'reused'
    assert article.full_content_retry_count == 3 and article.full_content_priority == 10
    assert article.full_content_next_attempt_at == future and article.full_content_task_created_at == initial


def test_force_creates_bounded_new_intent_without_erasing_old_failures(article):
    News.objects.filter(pk=article.pk).update(full_content_retry_count=3, full_content_next_attempt_at=None,
        full_content_fetch_status='failed')
    article.refresh_from_db()
    before = timezone.now()
    assert enqueue_fetch(article, force=True) == 'queued'
    assert article.full_content_retry_count == 3 and article.full_content_priority == 10
    assert article.full_content_task_created_at >= before
    created = article.full_content_task_created_at
    assert enqueue_fetch(article, force=True) == 'reused'
    assert article.full_content_task_created_at == created


def test_force_does_not_recreate_exhausted_task_or_call_health(article):
    News.objects.filter(pk=article.pk).update(full_content_retry_count=5, full_content_next_attempt_at=None,
        full_content_fetch_status='failed')
    article.refresh_from_db()
    from api.services.article_content import request_full_content
    with patch('api.services.article_content.worker_health') as health:
        assert request_full_content(article, force=True) == 'rejected'
    health.assert_not_called()
    assert enqueue_fetch(article, force=True) == 'rejected'
    article.refresh_from_db()
    assert article.full_content_retry_count == 5 and article.full_content_next_attempt_at is None


def test_raising_priority_keeps_owned_claim_and_queue_age(article):
    from api.services.full_content_status import claim_fetch, owns_fetch
    News.objects.filter(pk=article.pk).update(full_content_fetch_status='pending', full_content_next_attempt_at=None,
        full_content_retry_count=2)
    article.refresh_from_db()
    assert enqueue_fetch(article) == 'queued'
    assert claim_fetch(article)
    created, claimed = article.full_content_task_created_at, article._full_content_snapshot.claimed_at
    assert enqueue_fetch(article, force=True) == 'reused'
    assert owns_fetch(article) and article.last_full_content_attempt == claimed
    assert article.full_content_task_created_at == created and article.full_content_retry_count == 2


def test_queue_latency_uses_creation_time_and_excludes_failed_refresh_old_body(article):
    created = timezone.now() - timedelta(minutes=3)
    News.objects.filter(pk=article.pk).update(full_content_task_created_at=created,
        full_content_fetched_at=created + timedelta(seconds=20), full_content_state='complete', full_content='Known complete body.')
    News.objects.create(title='Old refresh', content='Summary', url='https://webkit.org/blog/123/old-refresh/',
        source=article.source, category=article.category, publish_time=timezone.now(),
        full_content_state='complete', full_content='Old valid body.', full_content_task_created_at=created,
        full_content_fetched_at=created-timedelta(minutes=1))
    out = StringIO()
    call_command('full_content_stats', '--json', stdout=out)
    result = json.loads(out.getvalue())
    assert result['queue']['oldest_task_created_at'] == str(created)
    assert result['queue_to_body_latency']['count'] == 1
    assert result['queue_to_body_latency']['average'] == '0:00:20'



def test_handler_response_429_is_counted_even_when_scrapy_receives_only_control_error():
    result = crawl_result({'finish_reason': 'finished', 'outcome': 'updated', 'entries_committed': 1,
                          'budget/http_status_count/429': 1, 'budget/physical_requests': 1,
                          'next_attempt_at': '2026-10-14T00:00:00+00:00'})
    assert result['outcome'] == 'rate_limited' and result['http_statuses'] == {'429': 1}
    assert result['responses'] == result['physical_requests'] == 1
    assert result['next_attempt_at'] == '2026-10-14T00:00:00+00:00'
    normal = crawl_result({'finish_reason': 'finished', 'budget/http_status_count/200': 2,
                          'downloader/response_status_count/200': 2, 'downloader/response_count': 2})
    assert normal['http_statuses'] == {'200': 2} and normal['responses'] == 2



def test_reviewed_quota_403_with_persistent_cooldown_is_rate_limited_not_auth_blocked():
    result = crawl_result({'finish_reason': 'finished', 'budget/http_status_count/403': 1,
                          'budget/rate_limited': 1, 'budget/physical_requests': 1})
    assert result['outcome'] == 'rate_limited' and result['rate_limited_responses'] == 1
    assert result['http_statuses'] == {'403': 1}
