"""The former subprocess backfill command is a bounded enqueue alias."""
from io import StringIO
from unittest.mock import patch
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from api.models import Category, News, Source


@pytest.fixture
def news(db):
    return News.objects.create(title='Bounded article', content='A summary.', publish_time=timezone.now(),
        url='https://webkit.org/blog/12/article/', content_kind='article',
        source=Source.objects.create(name='WebKit'), category=Category.objects.create(name='科技',slug='alias'))


@pytest.mark.parametrize('dry_run', [False,True])
def test_legacy_alias_never_runs_subprocess_or_article_provider(news, dry_run):
    output=StringIO()
    with patch('api.services.article_fetcher.fetch_article_markdown') as fetch, patch('subprocess.run') as process:
        call_command('backfill_full_content_scrapy', limit=1, dry_run=dry_run, sleep=2, progress_every=10, stdout=output)
    fetch.assert_not_called(); process.assert_not_called()
    news.refresh_from_db()
    assert news.full_content_fetch_status == ('pending' if dry_run else 'queued')
    assert news.full_content_backfill_source == '' and news.full_content_backfill_at is None
    assert news.full_content == ''


def test_legacy_unbounded_limit_is_rejected(news):
    with pytest.raises(CommandError): call_command('backfill_full_content_scrapy', limit=0)
