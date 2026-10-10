import threading

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.admin import LegacyChatArchiveAdmin
from api.models import Category, ChatSession, LegacyChatArchive, News, Source
from api.services.chat_history import (
    ChatConflict,
    append_assistant_message,
    append_user_message,
    clear_chat_history,
)


@pytest.fixture
def chat_news(db):
    category = Category.objects.create(name='Chat ownership', slug='chat-ownership')
    source = Source.objects.create(name='Chat ownership source', url='https://source.example.test')
    return News.objects.create(
        title='Chat ownership article',
        content='A test article.',
        full_content='Cached article content.',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://article.example.test/chat-ownership',
    )


@pytest.fixture
def chat_user(db):
    return User.objects.create_user(username='chat-owner', password='test-password')


@pytest.fixture
def other_chat_user(db):
    return User.objects.create_user(username='other-chat-owner', password='test-password')


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_requires_authenticated_session_for_all_methods(chat_news):
    client = APIClient()
    path = f'/api/news/{chat_news.pk}/chat/'

    assert client.get(path).status_code == 403
    assert client.post(path, {'question': 'hello'}, format='json').status_code == 403
    assert client.delete(path).status_code == 403
    assert ChatSession.objects.count() == 0


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_history_is_isolated_and_body_owner_fields_are_ignored(chat_news, chat_user, other_chat_user):
    saved = ChatSession.objects.create(
        user=chat_user,
        news=chat_news,
        messages=[{'role': 'user', 'content': 'private to A'}],
    )
    client_b = APIClient()
    client_b.force_login(other_chat_user)
    path = f'/api/news/{chat_news.pk}/chat/'

    assert client_b.get(path).json() == {'messages': []}
    assert client_b.delete(path).status_code == 200
    saved.refresh_from_db()
    assert saved.messages == [{'role': 'user', 'content': 'private to A'}]
    assert ChatSession.objects.filter(user=other_chat_user, news=chat_news).count() == 0

    client_a = APIClient()
    client_a.force_login(chat_user)
    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr('api.views.ensure_full_content', lambda _news: None)
        scoped.setattr('api.views.stream_chat', lambda *_args, **_kwargs: iter(['assistant reply']))
        scoped.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda _user: None)
        response = client_a.post(
            path,
            {
                'question': 'new question',
                'user': other_chat_user.pk,
                'user_id': other_chat_user.pk,
                'session_id': 999999,
            },
            format='json',
        )
        assert response.status_code == 200
        list(response.streaming_content)

    saved.refresh_from_db()
    assert saved.user_id == chat_user.pk
    assert saved.messages[-2:] == [
        {'role': 'user', 'content': 'new question'},
        {'role': 'assistant', 'content': 'assistant reply'},
    ]


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_writes_require_valid_session_csrf(chat_news, chat_user):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(chat_user)
    path = f'/api/news/{chat_news.pk}/chat/'

    assert client.post(path, {'question': 'hello'}, format='json').status_code == 403
    csrf_response = client.get('/api/auth/csrf/')
    token = csrf_response.cookies['csrftoken'].value
    assert client.post(path, {'question': 'hello'}, format='json', HTTP_X_CSRFTOKEN='wrong').status_code == 403

    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr('api.views.ensure_full_content', lambda _news: None)
        scoped.setattr('api.views.stream_chat', lambda *_args, **_kwargs: iter(['answer']))
        scoped.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda _user: None)
        response = client.post(path, {'question': 'hello'}, format='json', HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200
        list(response.streaming_content)

    assert ChatSession.objects.get(user=chat_user, news=chat_news).messages[-2:] == [
        {'role': 'user', 'content': 'hello'},
        {'role': 'assistant', 'content': 'answer'},
    ]


@pytest.mark.parametrize(
    ('question', 'error_code'),
    [
        (None, 'invalid_question'),
        (123, 'invalid_question'),
        ('', 'invalid_question'),
        ('  \n ', 'invalid_question'),
        ('x' * 8001, 'question_too_long'),
    ],
)
@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_invalid_question_is_rejected_before_fetch_search_or_provider(
    chat_news, chat_user, question, error_code,
):
    client = APIClient()
    client.force_login(chat_user)
    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr('api.views.ensure_full_content', lambda _news: pytest.fail('fetch ran'))
        scoped.setattr('api.views.stream_chat', lambda *_args, **_kwargs: pytest.fail('provider ran'))
        scoped.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda _user: None)
        from api.services.research import tools as research_tools
        scoped.setattr(research_tools, '_tool_search_web', lambda *_args, **_kwargs: pytest.fail('search ran'))
        response = client.post(
            f'/api/news/{chat_news.pk}/chat/',
            {'question': question, 'web_search': True},
            format='json',
        )

    assert response.status_code == 400
    assert response.json()['error_code'] == error_code
    assert ChatSession.objects.count() == 0


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_question_at_8000_characters_is_accepted(chat_news, chat_user, monkeypatch):
    client = APIClient()
    client.force_login(chat_user)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    monkeypatch.setattr('api.views.stream_chat', lambda *_args, **_kwargs: iter([]))
    monkeypatch.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda _user: None)

    response = client.post(
        f'/api/news/{chat_news.pk}/chat/',
        {'question': 'q' * 8000},
        format='json',
    )
    assert response.status_code == 200
    list(response.streaming_content)
    session = ChatSession.objects.get(user=chat_user, news=chat_news)
    assert session.messages[0] == {'role': 'user', 'content': 'q' * 8000}


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_cas_conflict_returns_409_without_discarding_existing_message(chat_news, chat_user, monkeypatch):
    saved = ChatSession.objects.create(user=chat_user, news=chat_news, messages=[{'role': 'user', 'content': 'kept'}])
    client = APIClient()
    client.force_login(chat_user)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    monkeypatch.setattr('api.views.append_user_message', lambda **_kwargs: (_ for _ in ()).throw(ChatConflict()))

    response = client.post(
        f'/api/news/{chat_news.pk}/chat/',
        {'question': 'retry'},
        format='json',
    )

    assert response.status_code == 409
    assert response.json()['error_code'] == 'chat_conflict'
    saved.refresh_from_db()
    assert saved.messages == [{'role': 'user', 'content': 'kept'}]


@pytest.mark.django_db
def test_clear_advances_generation_and_late_assistant_cannot_restore_history(chat_news, chat_user):
    started = append_user_message(user_id=chat_user.pk, news_id=chat_news.pk, content='question')
    session = ChatSession.objects.get(pk=started.session_id)

    assert clear_chat_history(user_id=chat_user.pk, news_id=chat_news.pk) is True
    session.refresh_from_db()
    assert session.messages == []
    assert session.revision == 2
    assert session.generation == 1
    with pytest.raises(ChatConflict, match='chat_conflict'):
        append_assistant_message(
            user_id=chat_user.pk,
            news_id=chat_news.pk,
            session_id=started.session_id,
            generation=started.generation,
            content='late answer',
        )
    session.refresh_from_db()
    assert session.messages == []


@pytest.mark.django_db
def test_deleted_news_does_not_recreate_session_for_late_assistant(chat_news, chat_user):
    started = append_user_message(user_id=chat_user.pk, news_id=chat_news.pk, content='question')
    chat_news.delete()

    with pytest.raises(ChatConflict, match='chat_conflict'):
        append_assistant_message(
            user_id=chat_user.pk,
            news_id=chat_news.pk,
            session_id=started.session_id,
            generation=started.generation,
            content='late answer',
        )
    assert ChatSession.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_users_create_separate_sessions_for_same_news(chat_news, chat_user, other_chat_user):
    barrier = threading.Barrier(3)
    failures = []

    def append_for(user, content):
        from django.db import close_old_connections

        close_old_connections()
        try:
            barrier.wait(timeout=2)
            append_user_message(user_id=user.pk, news_id=chat_news.pk, content=content)
        except Exception as error:  # collected for a deterministic assertion in the caller
            failures.append(error)
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=append_for, args=(chat_user, 'A')),
        threading.Thread(target=append_for, args=(other_chat_user, 'B')),
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads), 'chat creation worker exceeded its join deadline'
    assert failures == []
    assert ChatSession.objects.filter(news=chat_news).count() == 2
    assert set(ChatSession.objects.filter(news=chat_news).values_list('user_id', flat=True)) == {
        chat_user.pk, other_chat_user.pk,
    }


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_user_appends_preserve_both_messages(chat_news, chat_user):
    barrier = threading.Barrier(3)
    failures = []

    def append(content):
        from django.db import close_old_connections

        close_old_connections()
        try:
            barrier.wait(timeout=2)
            append_user_message(user_id=chat_user.pk, news_id=chat_news.pk, content=content)
        except Exception as error:
            failures.append(error)
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=append, args=('A',)),
        threading.Thread(target=append, args=('B',)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads), 'chat append worker exceeded its join deadline'
    assert failures == []
    session = ChatSession.objects.get(user=chat_user, news=chat_news)
    assert {message['content'] for message in session.messages} == {'A', 'B'}
    assert session.revision == 2


@pytest.mark.django_db
def test_archive_admin_is_read_only_and_superuser_only(chat_user):
    site = admin.AdminSite()
    model_admin = LegacyChatArchiveAdmin(LegacyChatArchive, site)
    factory = RequestFactory()
    request = factory.get('/admin/api/legacychatarchive/')
    request.user = chat_user
    staff = User.objects.create_user(username='archive-staff', is_staff=True)
    staff_request = factory.get('/admin/api/legacychatarchive/')
    staff_request.user = staff
    superuser = User.objects.create_superuser(
        username='archive-admin', email='archive-admin@example.test', password='test-password',
    )
    admin_request = factory.get('/admin/api/legacychatarchive/')
    admin_request.user = superuser

    assert model_admin.has_view_permission(request) is False
    assert model_admin.has_view_permission(staff_request) is False
    assert model_admin.has_view_permission(admin_request) is True
    assert model_admin.has_add_permission(admin_request) is False
    assert model_admin.has_change_permission(admin_request) is False
    assert model_admin.has_delete_permission(admin_request) is False
