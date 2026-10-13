"""Operator commands persist intent, never perform article HTTP."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from api.models import Category, News, NewsSourceItem, Source, RequestBudget


@pytest.fixture
def make_news(db):
    source = Source.objects.create(name='WebKit', url='https://webkit.org')
    category = Category.objects.create(name='科技', slug='tech-batch')
    def create(identity=1, **extra):
        defaults = dict(title=f'Article {identity}', content='A summary.', publish_time=timezone.now(),
                        source=source, category=category, url=f'https://webkit.org/blog/{identity}/article/', content_kind='article')
        defaults.update(extra)
        return News.objects.create(**defaults)
    return create


def command(*args, **kwargs):
    output = StringIO()
    with patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        call_command('fetch_full_content', *args, stdout=output, **kwargs)
    fetch.assert_not_called()
    return output.getvalue()


def test_command_queues_selected_missing_body_without_attempt_timestamp(make_news):
    news = make_news()
    assert 'QUEUED' in command('--limit', '1')
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'queued' and news.full_content_next_attempt_at
    assert news.last_full_content_attempt is None and news.full_content_retry_count == 0
    assert news.full_content == ''


def test_dry_run_is_read_only(make_news):
    news = make_news()
    assert 'DRY-RUN' in command('--dry-run')
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'pending' and news.full_content_next_attempt_at is None


def test_status_retry_source_and_date_filters_are_preserved(make_news):
    selected = make_news(full_content_fetch_status='network_error')
    excluded = make_news(2, full_content_fetch_status='failed')
    exhausted = make_news(3, full_content_retry_count=5)
    command('--status', 'network_error', '--source', 'webkit', '--since', (timezone.now()-timedelta(days=1)).isoformat())
    selected.refresh_from_db(); excluded.refresh_from_db(); exhausted.refresh_from_db()
    assert selected.full_content_fetch_status == 'queued'
    assert excluded.full_content_fetch_status == 'failed' and exhausted.full_content_fetch_status == 'pending'


def test_force_preserves_owned_fetch_lease_retry_count_and_cooldown(make_news):
    future = timezone.now() + timedelta(hours=1)
    news = make_news(full_content='Readable old body.', full_content_state='complete', full_content_revision=3,
        full_content_fetch_status='fetching', last_full_content_attempt=timezone.now(), full_content_retry_count=2,
        full_content_next_attempt_at=future)
    attempt = news.last_full_content_attempt
    RequestBudget.objects.create(key='host:webkit.org', cooldown_until=future)
    assert 'REUSED' in command('--force', '--status', 'fetching')
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'fetching' and news.last_full_content_attempt == attempt
    assert news.full_content_retry_count == 2 and news.full_content_next_attempt_at == future
    assert RequestBudget.objects.get().cooldown_until == future


def test_existing_readable_body_is_cached_even_refresh_failed(make_news):
    news = make_news(full_content='Readable old body.', full_content_state='legacy', full_content_fetch_status='failed')
    command()
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'failed' and news.full_content_next_attempt_at is None


def test_recent_replenishment_requires_reliable_mapping_admission_and_advances_batches(make_news, settings):
    settings.FULL_CONTENT_AUTO_SOURCE_KEYS = {'webkit'}
    first, second, inferred = make_news(), make_news(2), make_news(3)
    for news in (first, second):
        NewsSourceItem.objects.create(source_key='webkit', upstream_id=str(news.pk), news=news, metadata={'publish_time_inferred': False})
    NewsSourceItem.objects.create(source_key='webkit', upstream_id='inferred', news=inferred, metadata={'publish_time_inferred': True})
    command('--recent-only', '--limit', '1')
    command('--recent-only', '--limit', '1')
    first.refresh_from_db(); second.refresh_from_db(); inferred.refresh_from_db()
    assert first.full_content_fetch_status == second.full_content_fetch_status == 'queued'
    command('--recent-only', '--limit', '1')
    inferred.refresh_from_db()
    assert inferred.full_content_next_attempt_at is None


@pytest.mark.parametrize('args', [('--limit','0'),('--limit','501'),('--max-retries','6'),('--since','2026-10-13'),('--until','bad')])
def test_command_rejects_unbounded_or_ambiguous_selection(make_news, args):
    make_news()
    with pytest.raises(CommandError): command(*args)
