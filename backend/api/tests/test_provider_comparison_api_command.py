from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
import io
import json
import pytest
from rest_framework.test import APIClient

from api.models import Category, News, ProviderComparison, Source
from api.services.article_fetcher.types import FetchResult


@pytest.fixture
def news(db):
    category = Category.objects.create(name='Provider API', slug='provider-api')
    source = Source.objects.create(name='Provider API Source', url='https://example.com')
    return News.objects.create(
        title='API Expected Title',
        content='API summary must not become markdown',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://example.com/api-provider-article',
        full_content='DO NOT UPDATE FROM COMPARISON',
    )


class ApiSuccessProvider:
    name = 'api_success'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title='API fetched title',
            markdown='API REAL MARKDOWN',
            quality_score=0.8,
        )


class ApiFailureProvider:
    name = 'api_failure'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=False,
            provider=self.name,
            url=url,
            error='api failure',
        )


def test_provider_comparison_api_post_get_list_and_retest(monkeypatch, news):
    def fake_provider_chain(provider_names=None):
        providers = [ApiSuccessProvider(), ApiFailureProvider()]
        if provider_names:
            return [provider for provider in providers if provider.name in provider_names]
        return providers

    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        fake_provider_chain,
    )
    user = User.objects.create_user(username='provider-user', password='test123')
    client = APIClient()
    client.force_login(user)

    post_response = client.post(
        '/api/provider-comparisons/',
        {'news_id': news.id, 'providers': ['api_success', 'api_failure']},
        format='json',
    )

    assert post_response.status_code == 201
    post_data = post_response.json()
    assert post_data['run_id']
    assert post_data['count'] == 2
    assert len(post_data['results']) == 2
    assert {item['provider'] for item in post_data['results']} == {'api_success', 'api_failure'}
    assert post_data['results'][0]['run_id'] == post_data['run_id']

    news.refresh_from_db()
    assert news.full_content == 'DO NOT UPDATE FROM COMPARISON'

    list_response = client.get('/api/provider-comparisons/')
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert 'results' in list_data
    assert 'adapted_sites' in list_data
    assert 'metrics' in list_data
    assert any(site['name'] == 'GitHub' and 'github.com' in site['domains'] for site in list_data['adapted_sites'])
    assert list_data['metrics']['total'] == 2
    assert list_data['metrics']['success'] == 1
    assert list_data['metrics']['failure'] == 1

    first_id = post_data['results'][0]['id']
    detail_response = client.get(f'/api/provider-comparisons/{first_id}/')
    assert detail_response.status_code == 200
    assert detail_response.json()['id'] == first_id

    retest_response = client.post(f'/api/provider-comparisons/{first_id}/retest/', {}, format='json')
    assert retest_response.status_code == 201
    assert retest_response.json()['count'] == 1
    assert ProviderComparison.objects.count() == 3


def test_provider_comparison_write_requires_authentication_and_csrf(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )
    user = User.objects.create_user(username='provider-admin', password='test123')

    anonymous = APIClient(enforce_csrf_checks=True)
    anonymous_response = anonymous.post(
        '/api/provider-comparisons/',
        {'news_id': news.id, 'providers': ['api_success']},
        format='json',
    )
    assert anonymous_response.status_code in (401, 403)

    no_csrf = APIClient(enforce_csrf_checks=True)
    no_csrf.force_login(user)
    no_csrf_response = no_csrf.post(
        '/api/provider-comparisons/',
        {'news_id': news.id, 'providers': ['api_success']},
        format='json',
    )
    assert no_csrf_response.status_code == 403

    with_csrf = APIClient(enforce_csrf_checks=True)
    with_csrf.force_login(user)
    csrf_response = with_csrf.get('/api/auth/csrf/')
    token = csrf_response.cookies['csrftoken'].value
    ok_response = with_csrf.post(
        '/api/provider-comparisons/',
        {'news_id': news.id, 'providers': ['api_success']},
        format='json',
        HTTP_X_CSRFTOKEN=token,
    )
    assert ok_response.status_code == 201


def test_provider_comparison_rejects_private_and_unadapted_urls(monkeypatch, db):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )
    user = User.objects.create_user(username='provider-admin', password='test123')
    client = APIClient()
    client.force_login(user)

    private_response = client.post(
        '/api/provider-comparisons/',
        {'url': 'http://127.0.0.1:8000/internal', 'providers': ['api_success']},
        format='json',
    )
    assert private_response.status_code == 400
    assert ProviderComparison.objects.count() == 0

    unadapted_response = client.post(
        '/api/provider-comparisons/',
        {'url': 'https://example.com/url-only', 'providers': ['api_success']},
        format='json',
    )
    assert unadapted_response.status_code == 400
    assert ProviderComparison.objects.count() == 0


def test_provider_comparison_rejects_unknown_providers(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [],
    )
    user = User.objects.create_user(username='provider-admin', password='test123')
    client = APIClient()
    client.force_login(user)

    response = client.post(
        '/api/provider-comparisons/',
        {'news_id': news.id, 'providers': ['typo']},
        format='json',
    )

    assert response.status_code == 400
    assert 'provider' in str(response.json()).lower()
    assert ProviderComparison.objects.count() == 0


def test_provider_comparison_api_url_only_request(monkeypatch, db):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )
    user = User.objects.create_user(username='provider-url-user', password='test123')
    client = APIClient()
    client.force_login(user)

    response = client.post(
        '/api/provider-comparisons/',
        {
            'url': 'https://github.com/example/url-only',
            'expected_title': 'URL Only Title',
            'summary': 'URL only summary',
            'providers': ['api_success'],
        },
        format='json',
    )

    assert response.status_code == 201
    data = response.json()
    assert data['count'] == 1
    assert data['results'][0]['news'] is None
    assert data['results'][0]['url'] == 'https://github.com/example/url-only'


def test_compare_providers_management_command_persists_results(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )

    call_command('compare_providers', '--news-id', str(news.id), '--providers', 'api_success')

    comparison = ProviderComparison.objects.get(provider='api_success')
    assert comparison.news == news
    assert comparison.markdown == 'API REAL MARKDOWN'
    news.refresh_from_db()
    assert news.full_content == 'DO NOT UPDATE FROM COMPARISON'


def test_compare_providers_management_command_json_serializes_uuid(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )
    out = io.StringIO()

    call_command(
        'compare_providers',
        '--news-id', str(news.id),
        '--providers', 'api_success',
        '--json',
        stdout=out,
    )

    data = json.loads(out.getvalue())
    assert isinstance(data['run_id'], str)
    assert data['count'] == 1
    assert data['results'][0]['run_id'] == data['run_id']


def test_compare_providers_management_command_rejects_unknown_provider(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [],
    )

    with pytest.raises(Exception) as exc_info:
        call_command('compare_providers', '--news-id', str(news.id), '--providers', 'typo')

    assert 'Unknown provider' in str(exc_info.value)

def test_compare_providers_management_command_rejects_private_url(monkeypatch, db):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )

    with pytest.raises(Exception) as exc_info:
        call_command(
            'compare_providers',
            '--url', 'http://127.0.0.1:8000/internal',
            '--providers', 'api_success',
        )

    assert 'Private or local' in str(exc_info.value)
    assert ProviderComparison.objects.count() == 0


def test_compare_providers_management_command_rejects_unadapted_url(monkeypatch, db):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.get_provider_chain',
        lambda provider_names=None: [ApiSuccessProvider()],
    )

    with pytest.raises(Exception) as exc_info:
        call_command(
            'compare_providers',
            '--url', 'https://example.com/url-only',
            '--providers', 'api_success',
        )

    assert 'adapted' in str(exc_info.value)
    assert ProviderComparison.objects.count() == 0

