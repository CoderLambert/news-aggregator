from datetime import timedelta
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from api.models import Category, News, Source, RequestBudget
from api.management.commands.auto_fetch_full_content import _fetch_one


@pytest.fixture
def make_news(db):
    source=Source.objects.update_or_create(name='WebKit', defaults={'url': 'https://webkit.org', 'language': 'en'})[0]
    category=Category.objects.create(name='科技',slug='fetch-api')
    def create(**extra):
        values=dict(title='Publisher title',url='https://webkit.org/blog/12/article/', content='A summary.',
                    source=source,category=category,publish_time=timezone.now(),content_kind='article')
        values.update(extra)
        return News.objects.create(**values)
    return create


@pytest.fixture
def client(db):
    value=Client()
    value.force_login(get_user_model().objects.create_user(username='fetch-reader',password='unused'))
    return value


@pytest.fixture(autouse=True)
def no_publisher_io():
    with patch('api.services.article_content.worker_health',return_value=True) as health, \
         patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        yield health,fetch
        fetch.assert_not_called()


def test_post_queues_detail_schema_and_location_without_network(client,make_news):
    news=make_news()
    response=client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 202
    data=response.json()
    assert data['id'] == news.pk and data['full_content'] == '' and data['has_full_content'] is False
    assert data['full_content_state'] == 'missing' and data['full_content_fetch_status'] == 'queued'
    assert data['full_content_next_attempt_at'] and data['last_full_content_attempt'] is None
    assert response['Location'].endswith(f'/api/news/{news.pk}/') and int(response['Retry-After']) >= 2
    news.refresh_from_db()
    assert news.full_content == '' and news.full_content_retry_count == 0
    assert news.full_content_priority == 10


def test_reader_request_promotes_existing_background_task(client, make_news):
    due = timezone.now() - timedelta(minutes=1)
    news = make_news(full_content_fetch_status='queued', full_content_next_attempt_at=due,
                     full_content_priority=0)
    response = client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 202
    news.refresh_from_db()
    assert news.full_content_priority == 10
    assert news.full_content_next_attempt_at == due


@pytest.mark.parametrize('state',['legacy','complete'])
def test_cached_readable_body_returns_200_even_worker_unavailable_and_last_refresh_failed(client,make_news,no_publisher_io,state):
    no_publisher_io[0].return_value=False
    news=make_news(full_content='Readable old body.',full_content_state=state,full_content_fetch_status='network_error')
    response=client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 200 and response.json()['has_full_content'] is True
    assert response.json()['full_content'] == 'Readable old body.'


@pytest.mark.parametrize('body',['','  \n  ','\u2003\u00a0'])
def test_empty_or_whitespace_success_is_queued_not_reported_as_available(client,make_news,body):
    news=make_news(full_content=body,full_content_state='complete',full_content_fetch_status='success')
    response=client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 202 and response.json()['has_full_content'] is False
    assert response.json()['full_content'] == ''


def test_disabled_or_stale_worker_returns_503_without_creating_intent(client,make_news,no_publisher_io):
    no_publisher_io[0].return_value=False
    news=make_news()
    response=client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 503 and response.json()['error_code'] == 'full_content_worker_unavailable'
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'pending' and news.full_content_next_attempt_at is None


@pytest.mark.parametrize('values', [dict(url=''),dict(url='https://example.com/unknown-article'),dict(url='https://www.reuters.com/world/story/'),dict(content_kind='product'),dict(full_content_fetch_status='blocked')])
def test_invalid_identity_or_unsupported_policy_is_422_before_worker_availability(client,make_news,no_publisher_io,values):
    no_publisher_io[0].return_value=False
    news=make_news(**values)
    response=client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 422 and response.json()['error_code'] in {'invalid_identity','unsupported'}
    news.refresh_from_db()
    assert news.full_content_next_attempt_at is None


@pytest.mark.parametrize('state',['queued','rate_limited','fetching'])
def test_repeated_post_reuses_intent_retry_count_and_current_lease(client,make_news,state):
    future=timezone.now()+timedelta(hours=1)
    attempt=timezone.now() if state == 'fetching' else None
    news=make_news(full_content_fetch_status=state,full_content_next_attempt_at=future,full_content_retry_count=2,last_full_content_attempt=attempt)
    for _ in range(2):
        assert client.post(f'/api/news/{news.pk}/fetch-full/',{'force':True},content_type='application/json').status_code == 202
    news.refresh_from_db()
    assert news.full_content_fetch_status == state and news.full_content_next_attempt_at == future
    assert news.last_full_content_attempt == attempt and news.full_content_retry_count == 2


def test_literal_true_requests_refresh_with_priority_without_bypassing_cooldown(client,make_news):
    news=make_news(full_content='Readable old body.',full_content_state='complete',full_content_fetch_status='success')
    assert client.post(f'/api/news/{news.pk}/fetch-full/',{'force':'true'},content_type='application/json').status_code == 200
    future=timezone.now()+timedelta(hours=1)
    RequestBudget.objects.create(key='host:webkit.org',cooldown_until=future)
    response=client.post(f'/api/news/{news.pk}/fetch-full/',{'force':True},content_type='application/json')
    assert response.status_code == 202 and response.json()['full_content'] == 'Readable old body.'
    assert int(response['Retry-After']) >= 3599
    news.refresh_from_db()
    assert news.full_content_next_attempt_at >= future and news.full_content_priority == 10
    assert news.full_content_revision == 0


def test_get_poll_is_read_only_and_does_not_enqueue(client,make_news):
    news=make_news()
    assert client.get(f'/api/news/{news.pk}/').status_code == 200
    assert client.get(f'/api/news/{news.pk}/fetch-full/').status_code == 405
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'pending' and news.full_content_next_attempt_at is None


def test_session_auth_and_csrf_remain_required(make_news):
    news=make_news()
    client=Client(enforce_csrf_checks=True)
    assert client.post(f'/api/news/{news.pk}/fetch-full/').status_code in {401,403}
    user=get_user_model().objects.create_user(username='csrf-reader',password='unused')
    client.force_login(user)
    assert client.post(f'/api/news/{news.pk}/fetch-full/').status_code == 403
    token=client.get('/api/auth/csrf/').cookies['csrftoken'].value
    response=client.post(f'/api/news/{news.pk}/fetch-full/',HTTP_ORIGIN='http://127.0.0.1:5173',HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 202


def test_background_worker_does_not_fetch_after_losing_atomic_claim(make_news):
    news=make_news()
    with patch('api.services.full_content_worker.claim_fetch',return_value=False) as claim, \
         patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        assert _fetch_one(news) is None
    claim.assert_called_once_with(news)
    fetch.assert_not_called()



def test_force_cannot_queue_exhausted_failures_even_with_healthy_worker(client, make_news, no_publisher_io):
    news = make_news(full_content_fetch_status='failed', full_content_retry_count=5)
    response = client.post(f'/api/news/{news.pk}/fetch-full/', data={'force': True}, content_type='application/json')
    assert response.status_code == 422 and response.json()['error_code'] == 'retry_exhausted'
    no_publisher_io[0].assert_not_called()
    news.refresh_from_db()
    assert news.full_content_next_attempt_at is None and news.full_content_retry_count == 5
