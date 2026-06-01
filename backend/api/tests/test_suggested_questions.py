"""Tests for the suggested-questions endpoint.

POST /api/news/:id/suggested-questions/
  - On first call: invokes LLM, persists the result on news.suggested_questions
  - On subsequent calls: returns cached questions without invoking LLM
  - On LLM error: falls back to the 3-question hardcoded list (always returns 200)
"""
from unittest.mock import patch
import pytest
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


@pytest.fixture
def news(db):
    cat = Category.objects.create(name='科技', slug='tech')
    src = Source.objects.create(name='TestSource', url='https://example.com')
    return News.objects.create(
        title='测试文章',
        content='这是一篇关于人工智能的文章，讨论了大模型在新闻领域的应用。',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/test',
    )


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
    with patch('api.views.get_clients', return_value=_fake_client(payload)):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    data = resp.json()
    assert 'questions' in data
    assert len(data['questions']) == 3
    assert data['questions'][0] == '这篇文章讲了什么？'

    # Cached on the News row
    news.refresh_from_db()
    assert len(news.suggested_questions) == 3
    assert news.suggested_questions_generated_at is not None


def test_second_call_uses_cache(news, client):
    news.suggested_questions = ['cached q1', 'cached q2', 'cached q3']
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
    with patch('api.views.get_clients', return_value=_fake_client('not json at all')):
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
    with patch('api.views.get_clients', return_value=_fake_client(new_payload)):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/?force=1')

    assert resp.status_code == 200
    assert resp.json()['questions'] == ['new q1', 'new q2', 'new q3']

    # Cache was overwritten, not appended
    news.refresh_from_db()
    assert news.suggested_questions == ['new q1', 'new q2', 'new q3']


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
