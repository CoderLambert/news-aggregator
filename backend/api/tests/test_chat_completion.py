"""NH-20: streamed chat completion evidence and owner fenced interruption."""
from api.tests.rss.reader_fixtures import public_legacy_article, without_article_context
import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Category, News, Source, ChatSession


@pytest.fixture
def chat_case(db, monkeypatch):
    author = User.objects.create_user(username='stream-owner', password='synthetic-test')
    source = Source.objects.create(name='Synthetic publisher', url='https://example.test')
    cat = Category.objects.create(name='synthetic', slug='synthetic')
    news = public_legacy_article(News.objects.create(
        title='A synthetic story', url='https://example.test/story', source=source,
        category=cat, publish_time=timezone.now(), content='safe summary'))
    monkeypatch.setattr('api.services.ai_execution.personal_clients_for_user', lambda _user: [(object(), 'test')])
    monkeypatch.setattr('socket.socket.connect', lambda *args, **kwargs: pytest.fail('reader initiated network'))
    monkeypatch.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda _: None)
    client = APIClient()
    client.force_login(author)
    return client, news, author


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_completed_turn_has_terminal_receipt_and_history_status(chat_case, monkeypatch):
    client, news, author = chat_case
    monkeypatch.setattr('api.views.stream_chat', lambda *a, **k: iter(['finished answer']))
    response = client.post(f'/api/news/{news.pk}/chat/', {'question': 'Explain'}, format='json')
    wire = b''.join(response.streaming_content).decode('utf-8')
    assert '"type": "chat_turn"' in wire and '"status": "complete"' in wire
    assert without_article_context(ChatSession.objects.get(news=news, user=author).messages[-1]) == {
        'role': 'assistant', 'content': 'finished answer', 'status': 'complete'}


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_provider_error_after_partial_stream_cannot_claim_complete(chat_case, monkeypatch):
    client, news, author = chat_case
    def broken(*_args, **_kwargs):
        yield 'verified beginning'
        raise RuntimeError('simulated provider break')
    monkeypatch.setattr('api.views.stream_chat', broken)
    response = client.post(f'/api/news/{news.pk}/chat/', {'question': 'Explain'}, format='json')
    wire = b''.join(response.streaming_content).decode('utf-8')
    assert '"status": "failed"' in wire
    session = ChatSession.objects.get(news=news, user=author)
    assert without_article_context(session.messages[-1]) == {'role': 'assistant', 'content': 'verified beginning', 'status': 'failed'}
    assert client.get(f'/api/news/{news.pk}/chat/').json()['messages'][-1]['status'] == 'failed'


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_disconnect_preserves_partial_as_interrupted(chat_case, monkeypatch):
    client, news, author = chat_case
    def streaming(*_args, **_kwargs):
        yield 'first partial'
        yield 'late partial'
    monkeypatch.setattr('api.views.stream_chat', streaming)
    response = client.post(f'/api/news/{news.pk}/chat/', {'question': 'Explain'}, format='json')
    output = iter(response.streaming_content)
    next(output)  # initial context metadata
    assert b'first partial' in next(output)
    response.close()  # Django closes the underlying generator on disconnect.
    stored = ChatSession.objects.get(news=news, user=author).messages
    assert without_article_context(stored[-1]) == {'role': 'assistant', 'content': 'first partial', 'status': 'interrupted'}


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_old_turn_remains_unknown_and_is_not_promoted_to_verified_context(chat_case, monkeypatch):
    client, news, author = chat_case
    ChatSession.objects.create(user=author, news=news, messages=[
        {'role': 'user', 'content': 'Old question'},
        {'role': 'assistant', 'content': 'Old answer without receipt'},
    ])
    assert client.get(f'/api/news/{news.pk}/chat/').json()['messages'] == [{'role': 'user', 'content': 'Old question'}]
    snapshots = []
    def capture(messages, **_kwargs):
        snapshots.append(messages)
        return iter(['new answer'])
    monkeypatch.setattr('api.views.stream_chat', capture)
    response = client.post(f'/api/news/{news.pk}/chat/', {'question': 'New question'}, format='json')
    list(response.streaming_content)
    assert not any(m.get('content') == 'Old answer without receipt' for m in snapshots[0])
    session = ChatSession.objects.get(news=news, user=author)
    assert session.messages[-1]['status'] == 'complete'
    assert session.messages[1] == {'role': 'assistant', 'content': 'Old answer without receipt'}
