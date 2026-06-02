"""Tests for the backfill_full_content_scrapy management command.

This command re-runs the *Scrapy-only* provider chain against articles that
don't yet have full_content, so the user can evaluate Scrapy quality
independently from Jina without polluting the main fetch path.

Key behaviours:
  - Uses ONLY ScrapySubprocessProvider (no Jina, no ScrapyHTTP fallback)
  - Serial execution with --sleep throttling
  - Skips validation_failed (Phase 2 plan convention)
  - Stamps full_content_backfill_source/at on success
  - Failures update status fields but do NOT stamp backfill fields
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import Category, News, Source
from api.services.article_fetcher import FetchError, FetchResult


@pytest.fixture
def src(db):
    return Source.objects.create(name='TestSource', url='https://example.com', language='en')


@pytest.fixture
def cat(db):
    return Category.objects.create(name='科技', slug='tech')


def _news(src, cat, **overrides):
    defaults = dict(
        title='示例文章',
        content='摘要内容',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/article',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


@pytest.mark.django_db
class TestBackfillScrapyCommand:
    def _call(self, **kwargs):
        kwargs.setdefault('sleep', 0)  # don't actually sleep in tests
        out = StringIO()
        call_command('backfill_full_content_scrapy', stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_does_not_invoke_provider_or_modify_db(self, src, cat):
        n = _news(src, cat)
        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown'
        ) as m:
            self._call(dry_run=True, limit=10)
        m.assert_not_called()
        n.refresh_from_db()
        assert n.full_content == ''
        assert n.full_content_backfill_source == ''
        assert n.full_content_backfill_at is None

    def test_success_writes_full_content_and_stamps_backfill_fields(self, src, cat):
        n = _news(src, cat)
        result = FetchResult(
            ok=True,
            provider='scrapy_subprocess',
            url=n.url,
            title=n.title,
            markdown='SCRAPY_FULL_BODY',
            quality_score=0.91,
        )
        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown',
            return_value=result,
        ) as m:
            self._call(limit=5)

        # Must have been called WITHOUT the default chain — pass a Scrapy-only provider list
        assert m.called
        kwargs = m.call_args.kwargs
        providers = kwargs.get('providers')
        assert providers is not None, 'backfill must pass an explicit providers chain (not None / default)'
        provider_names = [getattr(p, 'name', '') for p in providers]
        assert 'jina' not in provider_names, 'Jina must NOT be in backfill chain'
        assert 'scrapy_subprocess' in provider_names

        n.refresh_from_db()
        assert n.full_content == 'SCRAPY_FULL_BODY'
        assert n.full_content_fetch_status == 'success'
        assert n.full_content_fetch_provider == 'scrapy_subprocess'
        assert n.full_content_backfill_source == 'scrapy_subprocess'
        assert n.full_content_backfill_at is not None

    def test_failure_does_not_stamp_backfill_fields(self, src, cat):
        n = _news(src, cat, title='Article that Scrapy cannot fetch')
        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown',
            side_effect=FetchError('connection reset by peer'),
        ):
            self._call(limit=5)

        n.refresh_from_db()
        assert n.full_content == ''
        assert n.full_content_backfill_source == '', 'failure must NOT stamp backfill_source'
        assert n.full_content_backfill_at is None, 'failure must NOT stamp backfill_at'
        assert n.full_content_fetch_status == 'network_error'
        assert n.full_content_retry_count == 1

    def test_skips_articles_with_existing_full_content(self, src, cat):
        n = _news(src, cat, full_content='ALREADY_HAS_CONTENT', full_content_fetch_provider='jina')
        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown'
        ) as m:
            self._call(limit=10)
        m.assert_not_called()
        n.refresh_from_db()
        # Jina-fetched content untouched
        assert n.full_content == 'ALREADY_HAS_CONTENT'
        assert n.full_content_fetch_provider == 'jina'
        assert n.full_content_backfill_source == ''

    def test_skips_validation_failed_articles(self, src, cat):
        """validation_failed = rule problem, retrying same content is wasteful."""
        n = _news(src, cat, full_content_fetch_status='validation_failed')
        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown'
        ) as m:
            self._call(limit=10)
        m.assert_not_called()

    def test_respects_limit(self, src, cat):
        for i in range(5):
            _news(src, cat, url=f'https://example.com/a{i}', title=f'A{i}')
        called = []

        def _fake(url, **kwargs):
            called.append(url)
            return FetchResult(
                ok=True, provider='scrapy_subprocess', url=url, title='T',
                markdown='X' * 1000, quality_score=0.8,
            )

        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown',
            side_effect=_fake,
        ):
            self._call(limit=2)
        assert len(called) == 2

    def test_processes_failed_and_network_error_articles_too(self, src, cat):
        """Backfill should retry articles that previously failed via Jina."""
        n1 = _news(src, cat, url='https://example.com/n1',
                   full_content_fetch_status='failed', full_content_retry_count=1)
        n2 = _news(src, cat, url='https://example.com/n2',
                   full_content_fetch_status='network_error', full_content_retry_count=2)

        def _fake(url, **kwargs):
            return FetchResult(
                ok=True, provider='scrapy_subprocess', url=url, title='T',
                markdown='RECOVERED_BODY', quality_score=0.85,
            )

        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown',
            side_effect=_fake,
        ):
            self._call(limit=10)

        n1.refresh_from_db()
        n2.refresh_from_db()
        assert n1.full_content == 'RECOVERED_BODY'
        assert n1.full_content_backfill_source == 'scrapy_subprocess'
        assert n2.full_content == 'RECOVERED_BODY'
        assert n2.full_content_backfill_source == 'scrapy_subprocess'

    def test_sleep_throttle_invoked_between_requests(self, src, cat):
        _news(src, cat, url='https://example.com/a1', title='A1')
        _news(src, cat, url='https://example.com/a2', title='A2')

        def _fake(url, **kwargs):
            return FetchResult(
                ok=True, provider='scrapy_subprocess', url=url, title='T',
                markdown='OK_BODY' * 200, quality_score=0.9,
            )

        with patch(
            'api.management.commands.backfill_full_content_scrapy.fetch_article_markdown',
            side_effect=_fake,
        ), patch(
            'api.management.commands.backfill_full_content_scrapy.time.sleep'
        ) as m_sleep:
            self._call(limit=10, sleep=1.5)

        # Must throttle between items (called at least once with the right value)
        sleep_calls = [c.args[0] for c in m_sleep.call_args_list]
        assert 1.5 in sleep_calls, f'expected 1.5s throttle between items, got {sleep_calls}'
