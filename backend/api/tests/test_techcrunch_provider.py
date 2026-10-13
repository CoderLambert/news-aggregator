import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from django.utils import timezone

from api.models import News
from api.services.article_fetcher import fetch_article_markdown, FetchError
from api.services.article_fetcher.providers import TechCrunchWPProvider, ScrapyHTTPProvider, default_providers, DownloadedHTML
from api.services.article_fetcher.types import FetchResult
from api.services.news_ingestion import ingest_item
from api.services.full_content_status import enqueue_fetch, claim_fetch, mark_success
from newsaggregator.runtime_config import parse_runtime_config
from django.core.exceptions import ImproperlyConfigured

TARGET = 'https://techcrunch.com/2026/10/13/complete-post/'
TITLE = 'Complete publisher post'


def row(**changes):
    return dict(id=12, link=TARGET, date_gmt='2026-10-13T01:00:00', modified_gmt='2026-10-13T02:00:00',
                title={'rendered': TITLE}, content={'protected': False, 'rendered': '<p>Complete short post.</p>'},
                excerpt={'rendered': '<p>A summary.</p>'}, **changes)


class Response:
    def __init__(self, value, effective=None): self.value, self.effective = value, effective
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.value).encode()


def test_tc_flag_is_strict_and_default_off_before_network(settings):
    assert not parse_runtime_config({}).techcrunch_wp_enabled
    with pytest.raises(ImproperlyConfigured): parse_runtime_config({'TECHCRUNCH_WP_ENABLED': 'yes'})
    settings.TECHCRUNCH_WP_ENABLED = False
    with patch('api.services.article_fetcher.providers._open_url') as opened:
        assert not TechCrunchWPProvider().fetch(TARGET).ok
    opened.assert_not_called()
    assert not any(isinstance(p, TechCrunchWPProvider) for p in default_providers(TARGET))


def test_tc_slug_request_selects_exact_permalink_and_gmt_evidence(settings):
    settings.TECHCRUNCH_WP_ENABLED = True
    wrong = row()
    wrong['id'] = 99
    wrong['link'] = TARGET.replace('/2026/', '/2025/')
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response([wrong, row()])) as opened:
        result = TechCrunchWPProvider().fetch(TARGET, expected_title=TITLE)
    assert result.ok and result.candidate.source_item_id == '12'
    query = parse_qs(urlsplit(opened.call_args.args[0].full_url).query)
    assert query == {'slug': ['complete-post'], '_fields': ['id,link,date_gmt,modified_gmt,title,content,excerpt']}
    assert result.candidate.source_modified_at.hour == 2
    assert result.candidate.source_modified_at.utcoffset().total_seconds() == 0
    assert result.metadata['source_publish_time'] == '2026-10-13T01:00:00+00:00'


@pytest.mark.parametrize('wrong', ['link', 'protected', 'id', 'title', 'paywall', 'ambiguous'])
def test_tc_wrong_or_partial_payload_is_never_a_body_candidate(settings, wrong):
    settings.TECHCRUNCH_WP_ENABLED = True
    data = row()
    if wrong == 'link': data['link'] = TARGET.replace('complete-post', 'different-post')
    if wrong == 'protected': data['content']['protected'] = True
    if wrong == 'id': data['id'] = True
    if wrong == 'title': data['title']['rendered'] = 'Unrelated title'
    if wrong == 'paywall': data['content']['rendered'] = '<div data-paywall="true">Hidden remaining body.</div>'
    rows = [data, data] if wrong == 'ambiguous' else [data]
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(rows)):
        result = TechCrunchWPProvider().fetch(TARGET, expected_title=TITLE)
    assert not result.ok and result.candidate is None


def test_tc_domain_is_fixed_not_a_generic_cms_scanner(settings):
    settings.TECHCRUNCH_WP_ENABLED = True
    with patch('api.services.article_fetcher.providers._open_url') as opened:
        assert not TechCrunchWPProvider().fetch('https://css-tricks.com/2026/complete-post/').ok
    opened.assert_not_called()


@pytest.mark.parametrize('status', [401, 403, 429])
def test_tc_control_errors_end_chain_without_html_fallback(settings, status):
    settings.TECHCRUNCH_WP_ENABLED = True
    later = Mock(name='later')
    later.name = 'later'
    with patch('api.services.article_fetcher.providers._open_url', side_effect=HTTPError(TARGET, status, 'controlled', {}, None)):
        with pytest.raises(FetchError) as caught:
            fetch_article_markdown(TARGET, expected_title=TITLE, providers=[TechCrunchWPProvider(), later])
    assert caught.value.http_status == status
    later.fetch.assert_not_called()


@pytest.mark.django_db
def test_tc_numeric_cms_id_binds_to_existing_feed_guid_and_refresh_reuses_id(settings):
    settings.TECHCRUNCH_WP_ENABLED = True
    result = ingest_item(dict(source_key='techcrunch', upstream_id='https://techcrunch.com/?p=12',
        title=TITLE, url=TARGET, category_name='科技', content='A summary.', publish_time=timezone.now()))
    news = News.objects.get(pk=result.news_id)
    enqueue_fetch(news)
    assert claim_fetch(news)
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response([row()])):
        fetched = fetch_article_markdown(TARGET, expected_title=TITLE, news=news, providers=[TechCrunchWPProvider()])
    assert mark_success(news, fetched)
    news.refresh_from_db()
    assert news.full_content_revision == 1 and news.full_content_provenance['source_item_id'] == '12'
    assert news.source_items.get().upstream_id == 'https://techcrunch.com/?p=12'
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(row())) as opened:
        assert TechCrunchWPProvider().fetch(TARGET, expected_title=TITLE, news=news).ok
    assert urlsplit(opened.call_args.args[0].full_url).path == '/wp-json/wp/v2/posts/12'


@pytest.mark.parametrize('known_id,status,code', [(None, 404, 'unsupported'), (None, 405, 'unsupported'), ('12', 404, 'not_found'), ('12', 405, 'unsupported')])
def test_tc_api_unsupported_and_known_article_deletion_are_distinct(settings, known_id, status, code):
    from types import SimpleNamespace
    settings.TECHCRUNCH_WP_ENABLED = True
    news = SimpleNamespace(full_content_provenance={'source_key': 'techcrunch', 'source_item_id': known_id})
    with patch('api.services.article_fetcher.providers._open_url', side_effect=HTTPError(TARGET, status, 'controlled', {}, None)) as opened:
        result = TechCrunchWPProvider().fetch(TARGET, news=news)
    assert result.error_code == code
    assert opened.call_count == 1


@pytest.mark.django_db
def test_html_provider_uses_feed_identity_and_rejects_different_redirect_article():
    target = 'https://webkit.org/blog/12/original/'
    result = ingest_item(dict(source_key='webkit', upstream_id='opaque-guid', title=TITLE, url=target,
        category_name='科技', content='An excerpt.', publish_time=timezone.now()))
    news = News.objects.get(pk=result.news_id)
    raw = f'<html><head><link rel="canonical" href="{target}"></head><body><article><h1>{TITLE}</h1><p>' + ('Complete publisher prose. ' * 50) + '</p></article></body></html>'
    with patch.object(ScrapyHTTPProvider, '_download', return_value=DownloadedHTML(raw, target)):
        fetched = ScrapyHTTPProvider().fetch(target, expected_title=TITLE, news=news)
    assert fetched.ok and fetched.candidate.source_item_id == 'opaque-guid'
    with patch.object(ScrapyHTTPProvider, '_download', return_value=DownloadedHTML(raw, target.replace('original', 'different'))):
        assert not ScrapyHTTPProvider().fetch(target, expected_title=TITLE, news=news).ok
