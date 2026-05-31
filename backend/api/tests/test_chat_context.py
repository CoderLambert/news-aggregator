"""Tests for the chat/suggested-questions context selection logic.

Critical bug being fixed:
  Both NewsChatView and NewsSuggestedQuestionsView used to pick context as:
    context = news.full_content_zh if news.full_content_zh else news.content

  This skipped news.full_content entirely. If the user had clicked "fetch
  full article" but no Chinese translation existed yet, AI saw only the
  short list-preview blurb (news.content).

  Worse: if the user opened chat BEFORE clicking "fetch full article",
  there was no way for chat to ever see the real article body.

Fix:
  1. Context chain: full_content_zh -> full_content -> content_zh -> content
  2. ensure_full_content(news) auto-fetches via Jina if nothing is cached,
     so the user never has to click "fetch full article" before chatting.
"""
from unittest.mock import patch, MagicMock
import pytest
from django.utils import timezone
from api.models import News, Source, Category


@pytest.fixture
def src(db):
    return Source.objects.create(name='TestSource', url='https://example.com')


@pytest.fixture
def cat(db):
    return Category.objects.create(name='科技', slug='tech')


def _news(src, cat, **overrides):
    defaults = dict(
        title='测试文章',
        content='SHORT_PREVIEW',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/article',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


# ---------------------------------------------------------------------------
# pick_chat_context() — pure function, no I/O
# ---------------------------------------------------------------------------

class TestPickChatContext:
    def test_prefers_full_content_zh_when_present(self, src, cat):
        from api.views import pick_chat_context
        n = _news(src, cat,
                  content='SHORT', content_zh='SHORT_ZH',
                  full_content='FULL_EN', full_content_zh='FULL_ZH')
        assert pick_chat_context(n) == 'FULL_ZH'

    def test_falls_back_to_full_content_when_no_zh_translation(self, src, cat):
        from api.views import pick_chat_context
        n = _news(src, cat,
                  content='SHORT', content_zh='SHORT_ZH',
                  full_content='FULL_EN', full_content_zh='')
        assert pick_chat_context(n) == 'FULL_EN'

    def test_falls_back_to_content_zh_when_no_full(self, src, cat):
        from api.views import pick_chat_context
        n = _news(src, cat,
                  content='SHORT', content_zh='SHORT_ZH',
                  full_content='', full_content_zh='')
        assert pick_chat_context(n) == 'SHORT_ZH'

    def test_falls_back_to_content_as_last_resort(self, src, cat):
        from api.views import pick_chat_context
        n = _news(src, cat,
                  content='SHORT', content_zh='',
                  full_content='', full_content_zh='')
        assert pick_chat_context(n) == 'SHORT'


# ---------------------------------------------------------------------------
# ensure_full_content() — auto-fetch via Jina on first chat
# ---------------------------------------------------------------------------

class TestEnsureFullContent:
    def test_skips_fetch_when_full_content_already_present(self, src, cat):
        from api.views import ensure_full_content
        n = _news(src, cat, full_content='ALREADY_HERE')
        with patch('api.views._fetch_via_jina') as m:
            ensure_full_content(n)
        m.assert_not_called()
        n.refresh_from_db()
        assert n.full_content == 'ALREADY_HERE'

    def test_fetches_and_persists_when_empty(self, src, cat):
        from api.views import ensure_full_content
        n = _news(src, cat)
        with patch('api.views._fetch_via_jina', return_value='FRESHLY_FETCHED_BODY'):
            ensure_full_content(n)
        n.refresh_from_db()
        assert n.full_content == 'FRESHLY_FETCHED_BODY'
        assert n.full_content_fetched_at is not None

    def test_swallows_fetch_errors_silently(self, src, cat):
        """If Jina fails, chat should still work with whatever content we have."""
        from api.views import ensure_full_content
        n = _news(src, cat, content='SHORT_FALLBACK')
        with patch('api.views._fetch_via_jina', side_effect=RuntimeError('jina down')):
            # Must not raise — chat should degrade gracefully
            ensure_full_content(n)
        n.refresh_from_db()
        assert n.full_content == ''  # still empty
        assert n.content == 'SHORT_FALLBACK'  # caller can still use this

    def test_skips_fetch_when_no_url(self, src, cat):
        from api.views import ensure_full_content
        n = _news(src, cat, url='https://example.com/x', full_content='')
        n.url = ''  # simulate edge case
        n.save()
        with patch('api.views._fetch_via_jina') as m:
            ensure_full_content(n)
        m.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: NewsChatView auto-fetches before answering
# ---------------------------------------------------------------------------

class TestChatAutoFetch:
    def test_chat_view_auto_fetches_full_content_on_first_call(self, src, cat, client):
        n = _news(src, cat)
        assert n.full_content == ''

        # Mock both: Jina fetch + LLM stream
        def fake_stream(**kwargs):
            # Inspect the prompt to verify FULL content was passed
            sent = kwargs['messages'][0]['content']
            assert 'FETCHED_FULL_BODY' in sent, \
                f'Expected fetched content in prompt, got: {sent[:200]!r}'
            assert 'SHORT_PREVIEW' not in sent or 'FETCHED_FULL_BODY' in sent

            class _Stream:
                def __iter__(self):
                    chunk = MagicMock()
                    chunk.choices = [MagicMock()]
                    chunk.choices[0].delta.content = '回答'
                    yield chunk
            return _Stream()

        fake_client = MagicMock()
        fake_client.chat.completions.create = fake_stream

        with patch('api.views._fetch_via_jina', return_value='FETCHED_FULL_BODY') as m_fetch, \
             patch('api.views.get_clients', return_value=[(fake_client, 'doubao-seed-2.0-pro')]):
            resp = client.post(
                f'/api/news/{n.pk}/chat/',
                data={'question': '这文章讲啥？'},
                content_type='application/json',
            )
            # Consume the stream so generator finally runs
            list(resp.streaming_content)

        m_fetch.assert_called_once()
        n.refresh_from_db()
        assert n.full_content == 'FETCHED_FULL_BODY'

    def test_chat_view_does_not_refetch_when_full_content_exists(self, src, cat, client):
        n = _news(src, cat, full_content='ALREADY_CACHED')

        def fake_stream(**kwargs):
            class _Stream:
                def __iter__(self):
                    chunk = MagicMock()
                    chunk.choices = [MagicMock()]
                    chunk.choices[0].delta.content = '回答'
                    yield chunk
            return _Stream()

        fake_client = MagicMock()
        fake_client.chat.completions.create = fake_stream

        with patch('api.views._fetch_via_jina', side_effect=AssertionError('should not fetch')) as m_fetch, \
             patch('api.views.get_clients', return_value=[(fake_client, 'doubao-seed-2.0-pro')]):
            resp = client.post(
                f'/api/news/{n.pk}/chat/',
                data={'question': 'x'},
                content_type='application/json',
            )
            list(resp.streaming_content)
        m_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: suggested-questions also gets the fetched body
# ---------------------------------------------------------------------------

class TestSuggestedQuestionsAutoFetch:
    def test_suggested_questions_auto_fetches_too(self, src, cat, client):
        n = _news(src, cat)

        captured = {}

        class _Choice:
            def __init__(self, content):
                self.message = type('M', (), {'content': content})()

        class _Completion:
            def __init__(self, content):
                self.choices = [_Choice(content)]

        class _FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        captured['prompt'] = kwargs['messages'][0]['content']
                        return _Completion('["q1","q2","q3"]')

        with patch('api.views._fetch_via_jina', return_value='FETCHED_FULL_BODY'), \
             patch('api.views.get_clients', return_value=[(_FakeClient(), 'doubao-seed-2.0-pro')]):
            resp = client.post(f'/api/news/{n.pk}/suggested-questions/')

        assert resp.status_code == 200
        assert 'FETCHED_FULL_BODY' in captured['prompt']
