"""Every consumer honors body quarantine independently of raw text/hash."""
import ast
from datetime import timedelta
import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (
    Category, ChatGPTArticleTranslation, ChatGPTSubscriptionConnection, News,
    RequestBudget, SharedArticleTranslation, SharedArticleTranslationTask, Source, SourcePublication,
)
from api.serializers import NewsDetailSerializer
from api.services import article_content, shared_translations as shared
from api.services.full_content_status import correct_article_identity
from api.services.research import tools
from api.services.tts_service import resolve_tts_content, TTSContentUnavailable
from api.subscription_views import subscription_translation_response


pytestmark = pytest.mark.django_db
BODY = '# Source article\n\nThe complete original article retained for historical evidence.'
LEGACY_ZH = '历史完整译文仍保留在数据库。'
SUMMARY = 'Current metadata summary for the corrected publisher identity.'
SUMMARY_ZH = '当前真实身份的摘要。'


@pytest.fixture(autouse=True)
def local_consumers(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.CHATGPT_AUTH_MODE = 'local_oss'
    settings.DJANGO_ENV = 'development'
    from api.services import article_fetcher
    fetch = Mock(side_effect=AssertionError('consumer must not fetch a publisher'))
    monkeypatch.setattr(article_fetcher, 'fetch_article_markdown', fetch)
    yield
    fetch.assert_not_called()


@pytest.fixture
def make_news():
    source = Source.objects.update_or_create(name='Dev.to', defaults={'url': 'https://dev.to', 'language': 'en', 'source_type': 'news'})[0]
    SourcePublication.objects.update_or_create(source=source, defaults={'owner': 'legacy', 'reading_policy': 'standard'})
    category = Category.objects.create(name='Consumer regression', slug='consumer-regression')
    sequence = 0

    def create(**changes):
        nonlocal sequence
        sequence += 1
        defaults = dict(
            source=source, body_owner_source=source, category=category, title='availability corpus article',
            content=SUMMARY, content_zh=SUMMARY_ZH, title_zh='可读性测试文章',
            url=f'https://dev.to/team/consumer-{sequence}', publish_time=timezone.now(),
            content_kind='article', full_content=BODY, full_content_state='complete',
            full_content_zh=LEGACY_ZH, full_content_fetch_status='success',
            full_content_zh_fetched_at=timezone.now(),
        )
        defaults.update(changes)
        return News.objects.create(**defaults)

    return create


def reader():
    user = get_user_model().objects.create_user(username='content-consumer-reader')
    connection = ChatGPTSubscriptionConnection.objects.create(
        user=user, subject_hash='content-consumer-reader', issuer='https://auth.example.test',
        issued_client_id='synthetic-client', registration_key_hash=str(uuid.uuid4()),
        encrypted_access_token='synthetic-access', encrypted_refresh_token='synthetic-refresh',
        selected_model='synthetic-model', is_active=True, needs_reauth=False,
    )
    return user, connection


@pytest.fixture
def quarantined(make_news):
    news = make_news()
    user, connection = reader()
    digest = shared.source_hash(news.full_content)
    history = SharedArticleTranslation.objects.create(
        **shared.cache_key(news.pk, digest), content='历史共享译文', provider='chatgpt', completed_at=timezone.now(),
    )
    private = ChatGPTArticleTranslation.objects.create(
        user=user, connection=connection, news=news, source_hash=digest,
        content='历史私人译文', model_slug='synthetic-model', completed_at=timezone.now(),
    )
    task = SharedArticleTranslationTask.objects.create(
        **shared.cache_key(news.pk, digest), status='running',
        started_at=timezone.now(), expires_at=timezone.now() + timedelta(minutes=1),
    )
    from api.rss.legacy_fencing import capture_legacy_article
    token = capture_legacy_article(news, initialize=True)
    assert correct_article_identity(news, news.url + '-corrected', expected_url=news.url,
                                    expected_revision=news.full_content_revision, legacy_token=token)
    news.refresh_from_db()
    assert news.full_content == BODY
    assert shared.source_hash(news.full_content) == digest
    assert news.full_content_state == 'missing'
    return SimpleNamespace(news=news, user=user, connection=connection, digest=digest,
                           history=history, private=private, task=task)


def sse_payload(response):
    assert response['Content-Type'].startswith('text/event-stream')
    text = b''.join(response.streaming_content).decode('utf-8')
    records = [json.loads(line[6:]) for line in text.splitlines() if line.startswith('data: ')]
    assert len(records) == 1
    return records[0]


def test_quarantine_hides_original_and_all_translation_scopes_with_identical_source_hash(quarantined):
    record = quarantined
    request = APIRequestFactory().get('/')
    request.user = record.user
    data = NewsDetailSerializer(record.news, context={'request': request}).data

    assert data['full_content'] == ''
    assert data['full_content_zh'] == ''
    assert data['full_content_zh_fetched_at'] is None
    assert data['full_content_zh_source'] is None
    assert data['full_content_zh_scope'] is None
    assert data['has_full_content'] is False
    assert data['full_translation_personal_available'] is False
    assert data['full_translation_active'] is False
    assert article_content.pick_chat_context(record.news) == SUMMARY_ZH
    assert article_content.context_scope(record.news) == 'summary'
    assert shared.get_shared_translation(record.news) is None
    assert not shared.task_is_running(record.news)
    assert SharedArticleTranslation.objects.get(pk=record.history.pk).source_hash == record.digest
    assert ChatGPTArticleTranslation.objects.get(pk=record.private.pk).source_hash == record.digest


@pytest.mark.parametrize('with_lease', [False, True])
def test_shared_publication_rejects_quarantine_even_when_raw_body_hash_is_unchanged(quarantined, with_lease):
    record = quarantined
    lease = shared.TranslationLease(record.task.pk, record.task.lease_token) if with_lease else None

    with pytest.raises(shared.SharedTranslationError, match='原文已更新'):
        shared.publish_translation(news_id=record.news.pk, digest=record.digest,
                                   text='迟到翻译绝不能重新发布隔离正文', provider='chatgpt', lease=lease)

    record.history.refresh_from_db()
    record.task.refresh_from_db()
    assert record.history.content == '历史共享译文'
    assert SharedArticleTranslation.objects.count() == 1
    assert record.task.status == 'running'  # Lease mutation rolls back with rejection.
    assert record.news.full_content == BODY
    assert record.news.full_content_zh == LEGACY_ZH


def test_translation_endpoints_return_existing_sse_error_with_code_without_provider(quarantined, monkeypatch):
    from api.services import chatgpt_subscription_jobs, translation_jobs
    from api import views
    public_start = Mock(side_effect=AssertionError('public translation must not start'))
    private_start = Mock(side_effect=AssertionError('personal translation must not start'))
    provider_clients = Mock(side_effect=AssertionError('provider credentials must not be loaded'))
    monkeypatch.setattr(translation_jobs, 'start_or_get_job', public_start)
    monkeypatch.setattr(chatgpt_subscription_jobs, 'start_or_get_job', private_start)
    monkeypatch.setattr(views, 'get_clients', provider_clients)
    client = APIClient()
    client.force_authenticate(quarantined.user)

    response = client.post(f'/api/news/{quarantined.news.pk}/translate/', {'force': True}, format='json')
    public = sse_payload(response)
    request = APIRequestFactory().post('/', {'force': True}, format='json')
    request.user = quarantined.user
    personal = sse_payload(subscription_translation_response(request, quarantined.news, force=True))

    for payload in (public, personal):
        assert payload['error'] == '请先获取完整原文。'
        assert payload['error_code'] == 'full_content_not_ready'
        assert 'full_content_zh' not in payload
    public_start.assert_not_called()
    private_start.assert_not_called()
    provider_clients.assert_not_called()


@pytest.mark.parametrize('language', ['original', 'zh'])
def test_full_tts_rejects_quarantined_body_before_audio_provider(quarantined, language, monkeypatch):
    import edge_tts
    communicate = Mock(side_effect=AssertionError('quarantined full text must not reach speech provider'))
    monkeypatch.setattr(edge_tts, 'Communicate', communicate)
    client = APIClient()
    client.force_authenticate(quarantined.user)

    response = client.get(f'/api/news/{quarantined.news.pk}/tts/', {'scope': 'full', 'language': language})

    assert response.status_code == 409
    assert response.data['code'] == 'source_content_required'
    communicate.assert_not_called()
    with pytest.raises(TTSContentUnavailable) as caught:
        resolve_tts_content(quarantined.news, quarantined.user, language, 'full')
    assert caught.value.code == 'source_content_required'


@pytest.mark.parametrize('state', ['complete', 'legacy'])
@pytest.mark.parametrize('status', ['rate_limited', 'network_error'])
def test_refresh_failure_keeps_valid_body_readable_for_detail_chat_and_speech(make_news, state, status):
    news = make_news(full_content_state=state, full_content_fetch_status=status,
                     full_content_error_code=status, full_content_next_attempt_at=timezone.now() + timedelta(minutes=10))
    user = get_user_model().objects.create_user(username='readable-after-refresh-failure')
    data = NewsDetailSerializer(news).data

    assert data['has_full_content']
    assert data['full_content'] == BODY
    assert data['full_content_zh'] == LEGACY_ZH
    assert data['full_content_fetch_status'] == status
    assert article_content.pick_chat_context(news) == LEGACY_ZH
    assert article_content.context_scope(news) == 'full'
    assert resolve_tts_content(news, user, 'original', 'full').content == BODY
    assert resolve_tts_content(news, user, 'zh', 'full').content == LEGACY_ZH


@pytest.fixture
def availability_corpus(make_news):
    complete = make_news(full_content_state='complete', full_content_fetch_status='network_error')
    legacy = make_news(full_content_state='legacy', full_content_fetch_status='rate_limited')
    missing = make_news(full_content_state='missing', full_content_fetch_status='success')
    whitespace = make_news(full_content_state='complete', full_content_fetch_status='success', full_content=' \n\t\u00a0\u2003')
    empty = make_news(full_content_state='legacy', full_content_fetch_status='success', full_content='')
    return [complete, legacy, missing, whitespace, empty]


def test_list_full_content_filter_uses_readable_state_instead_of_last_attempt_status(availability_corpus):
    client = APIClient()
    response = client.get('/api/news/', {'full_content': 'true', 'search': 'availability', 'mode': 'keyword'})

    assert response.status_code == 200
    assert {item['id'] for item in response.data['results']} == {item.pk for item in availability_corpus[:2]}
    assert all(item['has_full_content'] for item in response.data['results'])


@pytest.mark.parametrize('mode', ['keyword', 'semantic', 'hybrid'])
@pytest.mark.parametrize('order_by', ['relevance', 'time'])
def test_research_search_full_content_filter_applies_after_all_search_modes(availability_corpus, mode, order_by, monkeypatch):
    from api.services import vector_store
    results = [(item.pk, .1) for item in availability_corpus]
    vector = SimpleNamespace(count=lambda: len(results), search=lambda *_args, **_kwargs: results)
    monkeypatch.setattr(vector_store, 'VectorStoreService', lambda: vector)

    report = tools._tool_search_news('availability', mode=mode, limit=10, full_content=True, order_by=order_by)

    assert {item['id'] for item in report['articles']} == {item.pk for item in availability_corpus[:2]}
    assert report['total'] == 2


def test_research_fetch_uses_common_enqueue_and_returns_truthful_queued_summary(make_news, monkeypatch):
    news = make_news(full_content_state='missing', full_content_fetch_status='pending', full_content_zh='')
    deadline = timezone.now() + timedelta(minutes=10)
    RequestBudget.objects.create(key='host:dev.to', cooldown_until=deadline)
    monkeypatch.setattr(article_content, 'worker_health', Mock(return_value=True))
    common_request = Mock(wraps=article_content.request_full_content)
    monkeypatch.setattr(article_content, 'request_full_content', common_request)

    report = tools._tool_fetch_article(news.pk)

    common_request.assert_called_once()
    news.refresh_from_db()
    assert report['task_outcome'] == 'queued'
    assert report['context_scope'] == report['source_scope'] == 'summary'
    assert report['content'] == SUMMARY_ZH
    assert report['full_content_state'] == 'missing'
    assert report['full_content_fetch_status'] == 'queued'
    assert report['next_attempt_at'] == news.full_content_next_attempt_at.isoformat()
    assert news.full_content_next_attempt_at >= deadline
    assert news.full_content == BODY  # Quarantine history remains, but was not read.


def test_research_fetch_unavailable_worker_returns_summary_without_false_success(make_news, monkeypatch):
    news = make_news(full_content_state='missing', full_content_fetch_status='pending')
    health = Mock(return_value=False)
    monkeypatch.setattr(article_content, 'worker_health', health)

    report = tools._tool_fetch_article(news.pk)

    health.assert_called_once_with(require_enabled=True)
    assert report['task_outcome'] == 'unavailable'
    assert report['error_code'] == 'full_content_worker_unavailable'
    assert report['context_scope'] == report['source_scope'] == 'summary'
    assert report['content'] == SUMMARY_ZH
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'pending'
    assert news.full_content_next_attempt_at is None


@pytest.mark.parametrize('state,source_scope', [('complete', 'full'), ('missing', 'summary')])
def test_research_fetch_caps_excerpt_and_distinguishes_original_scope(make_news, monkeypatch, state, source_scope):
    text = 'A long source paragraph. ' * 800
    news = make_news(full_content_state=state, full_content=text, content=text,
                     content_zh='', full_content_zh='', full_content_fetch_status='network_error')
    monkeypatch.setattr(article_content, 'worker_health', Mock(return_value=False))

    report = tools._tool_fetch_article(news.pk)

    assert report['content'] == text[:12000]
    assert len(report['content']) == 12000
    assert report['content_truncated']
    assert report['original_length'] == len(text)
    assert report['context_scope'] == 'excerpt'
    assert report['source_scope'] == source_scope
    assert report['task_outcome'] == ('cached' if state == 'complete' else 'unavailable')


def test_research_service_has_no_reverse_import_of_api_views():
    tree = ast.parse(inspect.getsource(tools))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {'api.views', 'api.subscription_views'}
            if node.module == 'api':
                assert not any(alias.name in {'views', 'subscription_views'} for alias in node.names)
        elif isinstance(node, ast.Import):
            assert not any(alias.name in {'api.views', 'api.subscription_views'} for alias in node.names)
