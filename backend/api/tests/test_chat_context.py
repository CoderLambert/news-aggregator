"""Current stored context without collector work."""
from api.tests.rss.reader_fixtures import public_legacy_article
from unittest.mock import patch
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from api.models import News, Source, Category
from api.services.article_content import pick_chat_context


@pytest.fixture
def make_news(db):
    source=Source.objects.update_or_create(name='WebKit', defaults={'url': 'https://webkit.org'})[0]
    category=Category.objects.create(name='科技',slug='context')
    def create(**extra):
        values=dict(title='Article title',content='SHORT_PREVIEW',url='https://webkit.org/blog/12/article/',
            source=source,category=category,publish_time=timezone.now(),content_kind='article')
        values.update(extra)
        return public_legacy_article(News.objects.create(**values))
    return create


@pytest.mark.parametrize('values,expected', [
    (dict(full_content='FULL_EN',full_content_zh='FULL_ZH',full_content_state='legacy'), 'FULL_ZH'),
    (dict(full_content='FULL_EN',content_zh='SHORT_ZH',full_content_state='complete',full_content_fetch_status='rate_limited'),'FULL_EN'),
    (dict(full_content='RETAINED_AUDIT',full_content_zh='OLD_TRANSLATION',full_content_state='missing',content_zh='SHORT_ZH'),'SHORT_PREVIEW'),
    (dict(content_zh='SHORT_ZH'),'SHORT_PREVIEW'),
    ({},'SHORT_PREVIEW'),
])
def test_current_context_requires_readable_body_before_full_translation_preference(make_news,values,expected):
    assert pick_chat_context(make_news(**values)) == expected


def test_original_context_keeps_full_body_when_current_translation_exists(make_news):
    news = make_news(
        full_content='FULL_EN', full_content_zh='FULL_ZH', full_content_state='legacy',
    )
    assert pick_chat_context(news, translation_mode='original') == 'FULL_EN'








@pytest.mark.parametrize('full', [False,True])
def test_chat_prompt_and_stream_scope_agree_and_never_fetch_article(make_news,client,full):
    news=make_news(**({'full_content':'READABLE_FULL_BODY','full_content_state':'legacy'} if full else {}))
    client.force_login(User.objects.create_user(username=f'context-reader-{full}'))
    captured={}
    def stream(messages,**kwargs):
        captured['prompt']=messages[0]['content']
        captured['evidence']=messages[1]['content']
        yield 'Answer.'
    with patch('api.services.ai_execution.personal_clients_for_user',return_value=[(object(),'model')]),patch('api.views.stream_chat',side_effect=stream), \
         patch('socket.socket.connect', side_effect=AssertionError('publisher IO')) as fetch:
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
    assert news.full_content_fetch_status == 'pending'


def test_summary_question_lowers_legacy_budget_without_shrinking_full_text(make_news, client):
    news = make_news(full_content='READABLE_FULL_BODY', full_content_state='legacy')
    client.force_login(User.objects.create_user(username='summary-budget'))
    captured = {}

    def stream(messages, **kwargs):
        captured['max_tokens'] = kwargs['max_tokens']
        captured['prompt'] = messages[0]['content']
        captured['evidence'] = messages[1]['content']
        yield '要点'

    with patch('api.services.ai_execution.personal_clients_for_user', return_value=[(object(), 'model')]), \
         patch('api.views.stream_chat', side_effect=stream):
        response = client.post(
            f'/api/news/{news.pk}/chat/',
            {'question': '帮我用一句话总结这篇文章'},
            content_type='application/json',
        )
        b''.join(response.streaming_content)
    assert response.status_code == 200
    assert captured['max_tokens'] == 512
    assert 'READABLE_FULL_BODY' in captured['evidence']
    assert '"evidence_policy": "full_article_body"' in captured['evidence']
    assert '约 180 个汉字' in captured['prompt']
    assert 'READABLE_FULL_BODY' not in captured['prompt']


def test_detail_question_keeps_legacy_output_ceiling(make_news, client):
    news = make_news(full_content='READABLE_FULL_BODY', full_content_state='legacy')
    client.force_login(User.objects.create_user(username='detail-budget'))
    captured = {}

    def stream(messages, **kwargs):
        captured['max_tokens'] = kwargs['max_tokens']
        captured['evidence'] = messages[1]['content']
        yield '展开'

    with patch('api.services.ai_execution.personal_clients_for_user', return_value=[(object(), 'model')]), \
         patch('api.views.stream_chat', side_effect=stream):
        response = client.post(
            f'/api/news/{news.pk}/chat/',
            {'question': '请详细分析这篇文章'},
            content_type='application/json',
        )
        b''.join(response.streaming_content)
    assert response.status_code == 200
    assert captured['max_tokens'] == 16000
    assert 'READABLE_FULL_BODY' in captured['evidence']


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
    with patch('api.services.ai_execution.personal_clients_for_user',return_value=[(Provider(),'model')]), \
         patch('api.views.get_clients',side_effect=AssertionError('site model must not be used')), \
         patch('socket.socket.connect', side_effect=AssertionError('publisher IO')) as fetch:
        response=client.post(f'/api/news/{news.pk}/suggested-questions/')
    fetch.assert_not_called()
    assert response.status_code == 200 and response.json()['context_scope'] == 'summary'
    assert 'SHORT_PREVIEW' in captured['prompt'] and '可用内容范围: summary' in captured['prompt']
