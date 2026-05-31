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
    """Return a mock OpenAI client whose .chat.completions.create returns content."""
    class _C:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeCompletion(content)
    return _C()


def test_first_call_invokes_llm_and_caches(news, client):
    payload = '["这篇文章讲了什么？", "AI 在新闻领域怎么用？", "有什么风险？"]'
    with patch('api.views.get_openai_client', return_value=_fake_client(payload)):
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
    with patch('api.views.get_openai_client', side_effect=AssertionError('should not call LLM')):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    assert resp.json()['questions'] == ['cached q1', 'cached q2', 'cached q3']


def test_llm_error_falls_back_to_default(news, client):
    with patch('api.views.get_openai_client', side_effect=RuntimeError('boom')):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    # Still 200 — UX-friendly: user always sees 3 chips
    assert resp.status_code == 200
    questions = resp.json()['questions']
    assert len(questions) == 3
    # Default hardcoded fallback
    assert '总结' in questions[0] or '观点' in questions[1] or '背景' in questions[2]


def test_invalid_json_response_falls_back(news, client):
    with patch('api.views.get_openai_client', return_value=_fake_client('not json at all')):
        resp = client.post(f'/api/news/{news.pk}/suggested-questions/')
    assert resp.status_code == 200
    assert len(resp.json()['questions']) == 3


def test_404_for_missing_news(db, client):
    resp = client.post('/api/news/999999/suggested-questions/')
    assert resp.status_code == 404
