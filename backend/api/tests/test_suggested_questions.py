"""Tests for the suggested-questions endpoint.

POST /api/news/:id/suggested-questions/
  - On first call: invokes LLM, persists the result on news.suggested_questions
  - On subsequent calls: returns cached questions without invoking LLM
  - On LLM error: falls back to the 3-question hardcoded list (always returns 200)
"""
from api.tests.rss.reader_fixtures import public_legacy_article
from unittest.mock import patch
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from api.models import News, Source, Category
from api.services.article_fetcher import FetchResult


@pytest.fixture(autouse=True)
def no_external_full_content_fetch():
    result = FetchResult(
        ok=True,
        provider='test',
        url='https://example.com/test',
        title='测试文章',
        markdown='测试文章\n\n这是真实抓取测试正文，用于隔离 suggested-questions 单测中的外部网络。' * 20,
    )
    with patch('api.views.fetch_article_markdown', return_value=result):
        yield


@pytest.fixture(autouse=True)
def authenticated_reader(db, client):
    client.force_login(User.objects.create_user(username='suggested-reader'))


@pytest.fixture
def news(db):
    cat = Category.objects.create(name='科技', slug='tech')
    src = Source.objects.create(name='TestSource', url='https://example.com')
    return public_legacy_article(News.objects.create(
        title='测试文章',
        content='这是一篇关于人工智能的文章，讨论了大模型在新闻领域的应用。',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/test',
    ))


class _FakeChoice:
    def __init__(self, content):
        self.message = type('M', (), {'content': content})()


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_client(content):
    """Return [(client, model)] list matching get_clients() output."""
    class _C:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeCompletion(content)
    return [(_C(), 'doubao-seed-2.0-pro')]


def test_first_call_invokes_llm_and_caches(news, client):
    payload = '["这篇文章讲了什么？", "AI 在新闻领域怎么用？", "有什么风险？"]'
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client(payload)):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    data = resp.json()
    assert 'questions' in data
    assert len(data['questions']) == 3
    assert data['questions'][0] == '这篇文章讲了什么？'

    # Cached on the News row
    news.refresh_from_db()
    assert len(news.suggested_questions['questions']) == 3
    assert news.suggested_questions_generated_at is not None


def test_second_call_uses_cache(news, client):
    from api.rss.access import get_stored_article
    from api.services.stored_readers import snapshot_metadata
    news.suggested_questions = {'questions': ['cached q1', 'cached q2', 'cached q3'],
        'article_context': snapshot_metadata(get_stored_article(None, news.pk))}
    news.suggested_questions_generated_at = timezone.now()
    news.save()

    # If LLM is invoked, this will raise — proving cache hit short-circuited it
    with patch('api.views.get_clients', side_effect=AssertionError('should not call LLM')):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    assert resp.json()['questions'] == ['cached q1', 'cached q2', 'cached q3']


def test_llm_error_falls_back_to_default(news, client):
    with patch('api.views.get_clients', return_value=[]):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    # Still 200 — UX-friendly: user always sees 3 chips
    assert resp.status_code == 200
    questions = resp.json()['questions']
    assert len(questions) == 3
    # Default hardcoded fallback
    assert '总结' in questions[0] or '观点' in questions[1] or '背景' in questions[2]


def test_invalid_json_response_falls_back(news, client):
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client('not json at all')):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    assert len(resp.json()['questions']) == 3


def test_404_for_missing_news(db, client):
    resp = client.post('/api/news/999999/suggested-questions/')
    assert resp.status_code == 404


def test_force_regenerate_bypasses_cache(news, client):
    """When the user clicks '换一批', the frontend passes force=1.
    Backend must re-invoke the LLM even though cache is warm.
    """
    news.suggested_questions = ['old q1', 'old q2', 'old q3']
    news.suggested_questions_generated_at = timezone.now()
    news.save()

    new_payload = '["new q1","new q2","new q3"]'
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client(new_payload)):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/?force=1')

    assert resp.status_code == 200
    assert resp.json()['questions'] == ['new q1', 'new q2', 'new q3']

    # Cache was overwritten, not appended
    news.refresh_from_db()
    assert news.suggested_questions['questions'] == ['new q1', 'new q2', 'new q3']


def test_force_regenerate_falls_back_on_llm_error(news, client):
    """Even on force-regen, an LLM failure must not break the UX —
    return the hardcoded fallback so the chips still render.
    Cached questions are preserved (not wiped) so we don't lose good data.
    """
    news.suggested_questions = ['old q1', 'old q2', 'old q3']
    news.suggested_questions_generated_at = timezone.now()
    news.save()

    with patch('api.views.get_clients', return_value=[]):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/?force=1')

    assert resp.status_code == 200
    assert len(resp.json()['questions']) == 3
    # Old cache untouched (failure shouldn't destroy good data)
    news.refresh_from_db()
    assert news.suggested_questions == ['old q1', 'old q2', 'old q3']


def test_slow_questions_do_not_overwrite_a_new_content_revision(news, client):
    class SlowClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    News.objects.filter(pk=news.pk).update(
                        full_content_revision=1, suggested_questions=['New question'],
                    )
                    return _FakeCompletion('["old 1", "old 2", "old 3"]')
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=[(SlowClient(), 'test-model')]):
        response = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 409
    assert response.json()['error_code'] == 'suggestion_content_changed'
    news.refresh_from_db()
    assert news.suggested_questions == ['New question']


def test_site_provider_is_never_charged_for_user_without_key(news, client):
    with (
        patch('api.views.get_clients', side_effect=AssertionError('site key must not be used')),
        patch('api.services.ai_execution.personal_clients_for_user', return_value=[]),
        patch('api.services.chatgpt_subscription.active_connection_for_user', return_value=None),
    ):
        response = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 200
    assert response.json()['generation'] == 'unconfigured'
    assert len(response.json()['questions']) == 3
    news.refresh_from_db()
    assert news.suggested_questions == []


def test_suggestion_budget_rejection_fences_any_billable_call(news, client):
    from api.services.account_security import RateLimitExceeded
    generator = _fake_client('["question a", "question b", "question c"]')
    news.suggested_questions = ['kept 1', 'kept 2', 'kept 3']
    news.save(update_fields=['suggested_questions'])
    with (
        patch('api.services.ai_execution.personal_clients_for_user', return_value=generator),
        patch('api.services.suggested_question_budget._reserve_buckets', side_effect=RateLimitExceeded(87)),
    ):
        response = client.post(f'/api/news/{news.pk}/suggested-questions/?force=1')
    assert response.status_code == 429
    assert response['Retry-After'] == '87'
    assert response.json()['error_code'] == 'suggestion_budget_exhausted'
    news.refresh_from_db()
    assert news.suggested_questions == ['kept 1', 'kept 2', 'kept 3']


def test_overlong_full_body_is_marked_excerpt_even_for_cached_questions(news, client):
    news.full_content = 'Original complete paragraph. ' * 400
    news.full_content_state = 'legacy'
    news.suggested_questions = ['q1', 'q2', 'q3']
    news.save(update_fields=['full_content', 'full_content_state', 'suggested_questions'])
    response = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 200
    assert response.json()['context_scope'] == 'excerpt'


def test_busy_suggestion_slot_never_calls_any_model(news, client):
    from api.services.suggested_question_budget import SuggestionCapacityBusy
    with (
        patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client('["a","b","c"]')),
        patch('api.services.suggested_question_budget._slots') as slots,
    ):
        slots.acquire.return_value = False
        response = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 429
    assert response.json()['error_code'] == 'suggestion_capacity_busy'
    assert int(response['Retry-After']) > 0


def test_two_accounts_cannot_pay_twice_for_the_same_article_revision(news, client):
    from api.services.account_security import RateLimitExceeded
    payload = '["this article?", "its impact?", "what next?"]'
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client(payload)):
        first = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert first.status_code == 200
    other = User.objects.create_user(username='other-suggested-reader')
    client.force_login(other)
    with patch('api.services.ai_execution.personal_clients_for_user', return_value=_fake_client(payload)):
        duplicate = client.post(f'/api/news/{news.pk}/suggested-questions/?force=1')
    assert duplicate.status_code == 429
    assert duplicate.json()['error_code'] == 'suggestion_budget_exhausted'
    assert int(duplicate['Retry-After']) > 0


def test_unconfigured_reader_does_not_enqueue_full_article(news, client):
    with (
        patch('api.views.ensure_full_content', side_effect=AssertionError('should not fetch')),
        patch('api.services.ai_execution.personal_clients_for_user', return_value=[]),
        patch('api.services.chatgpt_subscription.active_connection_for_user', return_value=None),
    ):
        response = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 200
    assert response.json()['generated'] is False
