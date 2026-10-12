import json
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.services.article_fetcher.providers import DevToAPIProvider, GitHubReadmeProvider, HackerNewsAPIProvider, default_providers
from api.services.structured_articles import dev_article_item, dev_candidate
from api.services.article_fetcher import fetch_article_markdown
from api.services.news_ingestion import ingest_item
from api.services.full_content_status import enqueue_fetch, claim_fetch, mark_success
from api.models import News


def payload(**extra):
    return dict(id=10, url='https://dev.to/person/article-10', title='Complete article',
                published_at='2026-10-01T10:00:00+08:00', edited_at='2026-10-02T09:00:00Z',
                description='An excerpt.', body_markdown='A complete short body.', **extra)


class Response:
    headers = {'content-type': 'application/json'}
    def __init__(self, value): self.value = value
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.value).encode()


def test_dev_fields_use_edited_at_without_fabricated_update_or_truncation():
    data = payload()
    data['edited_at'] = None
    data['updated_at'] = '2026-10-03T09:00:00Z'
    data['body_markdown'] = 'Paragraph.\n\n' * 900
    item = dev_article_item(data)
    candidate = dev_candidate(data, target_url=data['url'], retrieved_from_url='https://dev.to/api/articles/10', request_started_at=timezone.now())
    assert 'source_modified_at' not in item and candidate.source_modified_at is None
    assert len(candidate.raw_content) > 5000
    assert item['publish_time'].hour == 2


def test_specialized_default_chains_use_the_official_reading_object():
    assert [p.name for p in default_providers('https://dev.to/person/article-10')] == ['devto_api']
    assert [p.name for p in default_providers('https://news.ycombinator.com/item?id=10')] == ['hackernews_api']
    assert [p.name for p in default_providers('https://github.com/owner/repo')] == ['github_readme']


def test_dev_path_lookup_returns_verified_short_body_with_external_canonical_attribution():
    data = payload(canonical_url='https://webkit.org/blog/10/original/')
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(data)) as opened:
        result = DevToAPIProvider().fetch(data['url'], expected_title=data['title'])
    assert result.ok and result.candidate.source_item_id == '10'
    assert opened.call_args.args[0].full_url == 'https://dev.to/api/articles/person/article-10'
    assert result.candidate.declared_canonical_url == data['canonical_url']


@pytest.mark.parametrize('wrong', ['url', 'id', 'title'])
def test_dev_response_identity_and_title_must_match_requested_article(wrong):
    data = payload()
    if wrong == 'url': data['url'] = 'https://dev.to/person/different'
    if wrong == 'id': data['id'] = True
    if wrong == 'title': data['title'] = 'Unrelated publisher story'
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(data)):
        result = DevToAPIProvider().fetch(payload()['url'], expected_title=payload()['title'])
    assert not result.ok


@pytest.mark.django_db
def test_dev_worker_uses_known_id_and_typed_candidate_commits_only_owned_revision():
    data = payload()
    result = ingest_item(dev_article_item(data))
    news = News.objects.get(pk=result.news_id)
    enqueue_fetch(news)
    assert claim_fetch(news)
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(data)) as opened:
        fetched = fetch_article_markdown(news.url, expected_title=news.title, news=news, providers=[DevToAPIProvider()])
    assert opened.call_args.args[0].full_url == 'https://dev.to/api/articles/10'
    assert fetched.candidate.expected_revision == 0
    assert mark_success(news, fetched)
    news.refresh_from_db()
    assert news.full_content_state == 'complete' and news.full_content_revision == 1


def test_hn_wrong_item_id_stops_without_retargeting_external_url():
    with patch('api.services.article_fetcher.providers._open_url', return_value=Response(dict(id=99, type='story', url='https://example.com/article'))):
        result = HackerNewsAPIProvider().fetch('https://news.ycombinator.com/item?id=10')
    assert not result.ok and result.error_code == 'invalid_identity' and not result.metadata


@pytest.mark.django_db
def test_github_successful_raw_readme_path_is_reused_as_provenance():
    from api.models import Category, Source
    news = News.objects.create(title='owner/repo', url='https://github.com/owner/repo',
        publish_time=timezone.now(), category=Category.objects.create(name='Code', slug='code'),
        source=Source.objects.create(name='GitHub Trending'), content_kind='readme')
    preferred = 'https://raw.githubusercontent.com/owner/repo/master/README.md'
    news.full_content_provenance = {'retrieved_from_url': preferred}
    with patch.object(GitHubReadmeProvider, '_download', return_value='# owner/repo\n\nComplete short documentation.') as download:
        result = GitHubReadmeProvider().fetch(news.url, expected_title=news.title, news=news)
    assert result.ok and result.candidate.retrieved_from_url == preferred
    download.assert_called_once_with(preferred)
