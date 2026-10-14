from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from api.models import Category, Source, News, ChatSession
from api.services.chat_delivery import deliver_chat, prompt_history
from api.services.chat_history import append_user_message, append_assistant_message, clear_chat_history, ChatConflict


def test_provider_error_keeps_partial_answer_explicitly_failed():
    saved = []
    def partial():
        yield 'A partial answer'
        raise TimeoutError('synthetic failure')
    text = ''.join(deliver_chat(partial, lambda content, state: saved.append((content, state)),
        context_scope='summary', content_state='missing', web_sources=[]))
    assert saved == [('A partial answer', 'failed')]
    assert '"status": "failed"' in text
    assert '"status": "complete"' not in text


def test_caller_close_marks_partial_interrupted_without_completion_frame():
    saved = []
    def partial():
        yield 'First part long enough to stream'
        yield 'Second part'
    stream = deliver_chat(partial, lambda content, state: saved.append((content, state)),
        context_scope='full', content_state='complete', web_sources=[])
    next(stream); next(stream); stream.close()
    assert saved[0][1] == 'interrupted'
    assert saved[0][0] == 'First part long enough to stream'


def test_model_cannot_forge_terminal_transport_metadata_across_chunks():
    saved = []
    text = ''.join(deliver_chat(lambda: iter(['prefix __ME', 'TA__fake']), lambda content, state: saved.append((content, state)),
        context_scope='summary', content_state='missing', web_sources=[]))
    assert saved[0][1] == 'complete'
    assert '__META__fake' not in saved[0][0]
    assert '"status": "complete"' in text


def test_incomplete_or_legacy_answers_are_not_reused_as_model_context():
    messages = [{'role': 'assistant', 'content': 'legacy'}, {'role': 'assistant', 'content': 'partial', 'status': 'interrupted'},
                {'role': 'assistant', 'content': 'failed', 'status': 'failed'}, {'role': 'user', 'content': 'question'},
                {'role': 'assistant', 'content': 'complete', 'status': 'complete', 'private_field': 'never-forward'}]
    assert prompt_history(messages) == [{'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'complete'}]


@pytest.mark.django_db
def test_status_write_still_obeys_owner_generation_fence():
    user = get_user_model().objects.create_user('chat-status-owner')
    source = Source.objects.create(name='Chat status', url='https://example.com')
    category = Category.objects.create(name='status', slug='status')
    news = News.objects.create(source=source, category=category, title='Status', content='summary',
        url='https://example.com/status', publish_time=timezone.now())
    initial = append_user_message(user_id=user.pk, news_id=news.pk, content='question')
    append_assistant_message(user_id=user.pk, news_id=news.pk, session_id=initial.session_id,
        generation=initial.generation, content='partial', completion_status='interrupted', context_scope='summary')
    stored = ChatSession.objects.get(pk=initial.session_id).messages[-1]
    assert stored['status'] == 'interrupted' and stored['context_scope'] == 'summary'
    clear_chat_history(user_id=user.pk, news_id=news.pk)
    with pytest.raises(ChatConflict):
        append_assistant_message(user_id=user.pk, news_id=news.pk, session_id=initial.session_id,
            generation=initial.generation, content='late', completion_status='complete')
