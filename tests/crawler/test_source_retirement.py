"""Retired publishers cannot re-enter collection; local history remains intact."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from scrapy import Request

from api.management.commands.crawl import SPIDERS
from api.models import CrawlBatch, CrawlRun, CrawlerTarget, Category, News, Source
from api.crawler_serializers import CrawlRunSerializer
from api.crawler_views import CrawlerTargetDetailView, CrawlRunRetryView, target_queryset
from api.services.crawler_control import sync_crawler_targets, claim_next_run, create_crawl_batch, NoTargetsQueued
from api.services.source_policy import POLICIES
from api.services.news_ingestion import ingest_item
from api.services.full_content_status import enqueue_fetch, claim_fetch, has_full_content
from api.services.full_content_worker import execute_one
from api.services.article_fetcher import fetch_article_markdown, FetchError
from news_crawler.download_handlers import BudgetedHTTPDownloadHandler

RETIRED = ('leiphone', 'meta_ai', 'reuters', 'jiqizhixin', 'sanliu_kr')


def test_registry_contains_only_public_supported_channels():
    assert len(SPIDERS) == 51
    assert set(SPIDERS) == {key for key, policy in POLICIES.items() if not policy.unsupported_reason}
    assert all(key not in SPIDERS for key in RETIRED)


@pytest.mark.parametrize('key', RETIRED)
def test_retired_channel_blocks_transport_provider_and_reader_before_any_request(key):
    policy = POLICIES[key]
    url = 'https://' + policy.domains[0] + '/article/example'
    handler = object.__new__(BudgetedHTTPDownloadHandler)
    handler.crawler = SimpleNamespace(spider=SimpleNamespace(name=key))
    assert not handler._allowed(Request(policy.feed_url or url))
    provider = Mock()
    with pytest.raises(FetchError) as error:
        fetch_article_markdown(url, providers=[provider])
    assert error.value.failures[0].error_code == 'unsupported'
    provider.fetch.assert_not_called()
    assert ingest_item({'source_key': key}).receipt_outcome == 'policy_skip'
    from api.services.article_fetcher.providers import TrustedNewsJinaProvider
    with patch('api.services.article_fetcher.providers._open_url') as opened:
        assert TrustedNewsJinaProvider().fetch(url).error_code == 'unsupported'
    opened.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('key', RETIRED)
def test_retired_channel_disappears_from_management_but_retains_history_and_cancels_pending_work(key):
    target = CrawlerTarget.objects.create(spider_name=key, enabled=True)
    batch = CrawlBatch.objects.create(trigger='manual', total=2)
    old_run = CrawlRun.objects.create(target=target, batch=batch, status='failed', finished_at=timezone.now())
    queued = CrawlRun.objects.create(target=target, batch=batch)
    source = Source.objects.create(name=POLICIES[key].name)
    category = Category.objects.create(name='History', slug='history')
    news = News.objects.create(source=source, category=category, title='Saved article',
        url='https://' + POLICIES[key].domains[0] + '/article/example', publish_time=timezone.now(),
        full_content='Saved original article. ' * 100, full_content_state='complete',
        full_content_fetch_status='success')
    sync_crawler_targets()
    target.refresh_from_db(); queued.refresh_from_db(); news.refresh_from_db()
    assert not target.enabled
    assert not target_queryset().filter(pk=key).exists()
    assert queued.status == 'cancelled' and '移除' in queued.safe_error
    assert CrawlRun.objects.get(pk=old_run.pk).status == 'failed'
    assert CrawlRunSerializer(old_run).data['source_active'] is False
    assert News.objects.get(pk=news.pk).full_content == news.full_content
    assert has_full_content(news)
    assert enqueue_fetch(news, force=True) == 'rejected'
    assert claim_fetch(news, force=True) is None
    with pytest.raises(NoTargetsQueued):
        create_crawl_batch(trigger='retry', spider_names=[key])
    user = get_user_model().objects.create_user(username='retirement-admin', is_superuser=True)
    factory = APIRequestFactory()
    request = factory.patch('/targets/', {'enabled': True}, format='json')
    force_authenticate(request, user=user)
    assert CrawlerTargetDetailView.as_view()(request, spider_name=key).status_code == 404
    request = factory.post('/retry/')
    force_authenticate(request, user=user)
    assert CrawlRunRetryView.as_view()(request, run_id=old_run.pk).status_code == 409


@pytest.mark.django_db
def test_claim_skips_work_left_by_an_old_registry_and_keeps_other_channels():
    retired = CrawlerTarget.objects.create(spider_name='meta_ai', enabled=True)
    active = CrawlerTarget.objects.create(spider_name='webkit', enabled=True)
    batch = CrawlBatch.objects.create(trigger='manual', total=2)
    stale = CrawlRun.objects.create(target=retired, batch=batch)
    good = CrawlRun.objects.create(target=active, batch=batch)
    assert claim_next_run().pk == good.pk
    stale.refresh_from_db()
    assert stale.status == 'cancelled'
    active.refresh_from_db()
    assert active.enabled


@pytest.mark.django_db
def test_running_retired_crawl_is_cancelled_without_changing_finished_history():
    target = CrawlerTarget.objects.create(spider_name='leiphone', enabled=True)
    batch = CrawlBatch.objects.create(trigger='manual', total=1, status='running')
    run = CrawlRun.objects.create(target=target, batch=batch, status='running')
    sync_crawler_targets()
    run.refresh_from_db()
    assert run.status == 'cancel_requested'


@pytest.mark.django_db
def test_previously_queued_body_is_terminal_without_fetching():
    source = Source.objects.create(name='Meta AI')
    from api.models import SourcePublication
    SourcePublication.objects.create(source=source, owner='legacy')
    category = Category.objects.create(name='AI', slug='ai')
    news = News.objects.create(source=source, body_owner_source=source, category=category, title='Old queued article',
        url='https://ai.meta.com/blog/example/', publish_time=timezone.now(),
        full_content_fetch_status='queued', full_content_next_attempt_at=timezone.now())
    provider = Mock()
    assert execute_one(news, providers=[provider]) is None
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'unsupported' and news.full_content_next_attempt_at is None
    provider.fetch.assert_not_called()


@pytest.mark.parametrize('url', [
    'https://m.36kr.com/article/example', 'https://leiphone.com./article/example',
    'https://jiqizhixin.com/article/example', 'https://www.reuters.com/article/example',
    'https://ai.meta.com/blog/example/',
])
def test_retired_aliases_are_rejected_before_dns_or_network_access(url):
    from api.services.article_fetcher.safe_http import validate_public_url, UnsafeURL
    with patch('api.services.article_fetcher.safe_http._resolve_addrinfos') as dns:
        with pytest.raises(UnsafeURL) as error:
            validate_public_url(url)
    assert error.value.error_code == 'unsupported' and not error.value.retryable
    dns.assert_not_called()


def test_retirement_does_not_match_an_unrelated_domain_suffix():
    from api.services.source_policy import retired_policy_for_url
    assert retired_policy_for_url('https://notleiphone.com/article') is None
    assert retired_policy_for_url('https://reuters.com.example.org/article') is None
