"""Current readable context and shared enqueue intent, without request-time fetching."""
from unittest.mock import patch
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from api.models import News, Source, Category
from api.services.article_content import pick_chat_context,request_full_content
from api.views import ensure_full_content


@pytest.fixture
def make_news(db):
    source=Source.objects.update_or_create(name='WebKit', defaults={'url': 'https://webkit.org'})[0]
    category=Category.objects.create(name='科技',slug='context')
    def create(**extra):
        values=dict(title='Article title',content='SHORT_PREVIEW',url='https://webkit.org/blog/12/article/',
            source=source,category=category,publish_time=timezone.now(),content_kind='article')
        values.update(extra)
        return News.objects.create(**values)
    return create


@pytest.mark.parametrize('values,expected', [
    (dict(full_content='FULL_EN',full_content_zh='FULL_ZH',full_content_state='legacy'), 'FULL_ZH'),
    (dict(full_content='FULL_EN',content_zh='SHORT_ZH',full_content_state='complete',full_content_fetch_status='rate_limited'),'FULL_EN'),
    (dict(full_content='RETAINED_AUDIT',full_content_zh='OLD_TRANSLATION',full_content_state='missing',content_zh='SHORT_ZH'),'SHORT_ZH'),
    (dict(content_zh='SHORT_ZH'),'SHORT_ZH'),
    ({},'SHORT_PREVIEW'),
])
def test_current_context_requires_readable_body_before_full_translation_preference(make_news,values,expected):
    assert pick_chat_context(make_news(**values)) == expected


def test_ensure_full_content_persists_intent_without_fetching(make_news):
    news=make_news()
    with patch('api.services.article_content.worker_health',return_value=True),patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        assert ensure_full_content(news) == 'queued'
    fetch.assert_not_called()
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'queued' and news.full_content == ''
    assert news.last_full_content_attempt is None


def test_cancellation_before_enqueue_never_creates_task(make_news):
    news=make_news()
    def guard(): raise RuntimeError('controlled cancellation')
    with pytest.raises(RuntimeError): ensure_full_content(news,execution_guard=guard)
    news.refresh_from_db()
    assert news.full_content_next_attempt_at is None and news.full_content_retry_count == 0


def test_cancellation_after_enqueue_preserves_shared_durable_intent(make_news):
    news=make_news()
    calls=0
    def guard():
        nonlocal calls
        calls+=1
        if calls == 2: raise RuntimeError('controlled cancellation')
    with patch('api.services.article_content.worker_health',return_value=True),pytest.raises(RuntimeError):
        ensure_full_content(news,execution_guard=guard)
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'queued' and news.full_content_retry_count == 0


@pytest.mark.parametrize('full', [False,True])
def test_chat_prompt_and_stream_scope_agree_and_never_fetch_article(make_news,client,full):
    news=make_news(**({'full_content':'READABLE_FULL_BODY','full_content_state':'legacy'} if full else {}))
    client.force_login(User.objects.create_user(username=f'context-reader-{full}'))
    captured={}
    def stream(messages,**kwargs):
        captured['prompt']=messages[0]['content']
        captured['evidence']=messages[1]['content']
        yield 'Answer.'
    with patch('api.views.get_clients',return_value=[(object(),'model')]),patch('api.views.stream_chat',side_effect=stream), \
         patch('api.services.article_content.worker_health',return_value=True),patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        response=client.post(f'/api/news/{news.pk}/chat/',{'question':'Question?'},content_type='application/json')
        text=b''.join(response.streaming_content).decode()
    fetch.assert_not_called()
    scope='full' if full else 'summary'
    assert f'"context_scope": "{scope}"' in text
    assert '不可信数据' in captured['prompt']
    assert f'"context_scope": "{scope}"' in captured['evidence']
    assert ('READABLE_FULL_BODY' if full else 'SHORT_PREVIEW') in captured['evidence']
    assert 'READABLE_FULL_BODY' not in captured['prompt'] and 'SHORT_PREVIEW' not in captured['prompt']
    news.refresh_from_db()
    assert news.full_content_fetch_status == ('pending' if full else 'queued')


def test_suggestions_use_summary_scope_without_waiting_for_article_http(make_news,client):
    news=make_news()
    client.force_login(User.objects.create_user(username='suggestion-context'))
    captured={}
    class Provider:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured['prompt']=kwargs['messages'][0]['content']
                    from types import SimpleNamespace
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='["q1","q2","q3"]'))])
    with patch('api.services.provider_credentials.personal_clients_for_user',return_value=[(Provider(),'model')]), \
         patch('api.views.get_clients',side_effect=AssertionError('site model must not be used')), \
         patch('api.services.article_content.worker_health',return_value=True), \
         patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
        response=client.post(f'/api/news/{news.pk}/suggested-questions/')
    fetch.assert_not_called()
    assert response.status_code == 200 and response.json()['context_scope'] == 'summary'
    assert 'SHORT_PREVIEW' in captured['prompt'] and '可用内容范围: summary' in captured['prompt']
