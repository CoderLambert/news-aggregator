from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ResearchSession


def _csrf_token(client):
    response = client.get('/api/auth/csrf/')
    assert response.status_code == 200
    return response.cookies['csrftoken'].value


def _secure_post(client, path, data, token):
    return client.post(
        path,
        data,
        format='json',
        secure=True,
        HTTP_ORIGIN='https://testserver',
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.mark.django_db
def test_research_create_chat_and_delete_reject_missing_or_bad_csrf():
    user = User.objects.create_user(username='research-csrf-user', password='not-used')
    session = ResearchSession.objects.create(user=user, title='Owned session', messages=[])
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)

    create_without_token = client.post('/api/research/', {'query': 'local test'}, format='json')
    chat_without_token = client.post(
        f'/api/research/{session.pk}/chat/', {'query': 'follow up'}, format='json',
    )
    delete_without_token = client.delete(f'/api/research/{session.pk}/')
    assert create_without_token.status_code == 403
    assert chat_without_token.status_code == 403
    assert delete_without_token.status_code == 403
    assert ResearchSession.objects.filter(pk=session.pk).exists()

    token = _csrf_token(client)
    wrong_token = _secure_post(client, '/api/research/', {'query': 'local test'}, 'invalid-token')
    wrong_origin = client.post(
        '/api/research/',
        {'query': 'local test'},
        format='json',
        secure=True,
        HTTP_ORIGIN='https://attacker.example.test',
        HTTP_X_CSRFTOKEN=token,
    )
    assert wrong_token.status_code == 403
    assert wrong_origin.status_code == 403

    deleted = client.delete(
        f'/api/research/{session.pk}/',
        secure=True,
        HTTP_ORIGIN='https://testserver',
        HTTP_X_CSRFTOKEN=token,
    )
    assert deleted.status_code == 204
    assert not ResearchSession.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
def test_research_create_uses_standard_session_auth_and_valid_secure_csrf_without_network():
    user = User.objects.create_user(username='research-create-user', password='not-used')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    token = _csrf_token(client)
    fake_job = SimpleNamespace(done=False)

    with patch(
        'api.services.research.job_manager.start_or_get_research_job',
        return_value=fake_job,
    ) as start_job:
        response = _secure_post(client, '/api/research/', {'query': 'offline test'}, token)

    assert response.status_code == 200
    assert response['Session-ID']
    session = ResearchSession.objects.get(pk=response['Session-ID'])
    assert session.user_id == user.pk
    start_job.assert_called_once_with(session.id, session, 'offline test', local_only=False)


@pytest.mark.django_db
def test_research_detail_and_chat_keep_cross_user_404_after_csrf_validation():
    owner = User.objects.create_user(username='research-owner', password='not-used')
    other_user = User.objects.create_user(username='research-other', password='not-used')
    session = ResearchSession.objects.create(user=owner, title='Private session', messages=[])
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(other_user)
    token = _csrf_token(client)

    detail = client.get(f'/api/research/{session.pk}/')
    deleted = client.delete(
        f'/api/research/{session.pk}/',
        secure=True,
        HTTP_ORIGIN='https://testserver',
        HTTP_X_CSRFTOKEN=token,
    )
    chat = _secure_post(
        client,
        f'/api/research/{session.pk}/chat/',
        {'query': 'must not run'},
        token,
    )

    assert detail.status_code == 404
    assert deleted.status_code == 404
    assert chat.status_code == 404
    assert ResearchSession.objects.filter(pk=session.pk, user=owner).exists()


@pytest.mark.django_db
def test_research_session_list_still_allows_authenticated_safe_reads():
    user = User.objects.create_user(username='research-list-user', password='not-used')
    ResearchSession.objects.create(user=user, title='Visible to owner', messages=[], updated_at=timezone.now())
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.get('/api/research/sessions/')
    assert response.status_code == 200
    assert response.data['count'] == 1
