"""Explicit catalog IO and read-only diagnostics retain owner/credential fences."""
import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.db.models import F
from django.test import override_settings
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.ai_model_models import AICallAttempt, AIModelProbeAttempt
from api.tests.test_ai_unified_consumers import unified

pytestmark = pytest.mark.django_db


def discover_url(context):
    return context.models_url + 'discover/'


def diagnostic_url(context):
    return '/api/me/ai/connections/' + str(context.connection.pk) + '/diagnostics/'


def proxy_reply(body):
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(body).encode()
    response.__enter__.return_value = response
    return response


def test_discovery_is_explicit_none_and_does_not_create_probe_receipts(unified, settings):
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-synthetic-discovery-project-123456789'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY_FILE = ''
    with patch('api.services.ai_model_probe._OPENER.open', return_value=proxy_reply({
            'models': ['org/model:cloud'], 'truncated': False})) as network:
        response = unified.api.post(discover_url(unified), {}, format='json')
    assert response.status_code == 200, response.content
    assert response.data['models'] == ['org/model:cloud']
    assert network.call_count == 1
    request = network.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == 'http://127.0.0.1:4000/newshub/models/discover'
    assert body['api_key'] is None and body['metadata']['newshub_owner_id'] == unified.owner.pk
    assert body['metadata']['newshub_auth_mode'] == 'none'
    assert AICallAttempt.objects.count() == AIModelProbeAttempt.objects.count() == 0


def test_diagnostics_and_catalog_get_never_dispatch_model_or_catalog_io(unified):
    with patch('api.services.ai_model_probe._OPENER.open') as network:
        result = unified.api.get(diagnostic_url(unified))
        assert result.status_code == 200
        assert result.data['inference_test_status'] == 'not_run'
        assert result.data['connection_status'] == 'active'
        assert unified.api.get(unified.models_url.replace('/models/', '/model-catalog/')).status_code == 200
        assert unified.api.get(discover_url(unified)).status_code == 405
    network.assert_not_called()
    assert '127.0.0.1' not in json.dumps(result.data)
    assert 'allowed_ips' not in result.data and 'api_key' not in result.data


def test_discovery_owner_and_override_fail_before_network(unified):
    with patch('api.services.ai_model_probe._OPENER.open') as network:
        assert unified.api.post(discover_url(unified), {'api_base': 'https://unapproved.invalid'}, format='json').status_code == 400
        unified.api.force_authenticate(get_user_model().objects.create_user('discovery-other'))
        assert unified.api.post(discover_url(unified), {}, format='json').status_code == 404
        assert unified.api.get(diagnostic_url(unified)).status_code == 404
    network.assert_not_called()


def test_late_discovery_cannot_return_results_after_credential_revocation(unified, settings):
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-synthetic-discovery-project-123456789'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY_FILE = ''
    response = proxy_reply({})
    def revoke(_size):
        UserAIConnection.objects.filter(pk=unified.connection.pk).update(credential_epoch=F('credential_epoch') + 1)
        return b'{"models":["old-private-model"],"truncated":false}'
    response.read.side_effect = revoke
    with patch('api.services.ai_model_probe._OPENER.open', return_value=response) as network:
        result = unified.api.post(discover_url(unified), {}, format='json')
    assert result.status_code in (409, 503)
    assert 'old-private-model' not in result.content.decode()
    assert network.call_count == 1


def test_discovery_requires_session_csrf_viewer_and_feature_gate(unified):
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(unified.owner)
    url = discover_url(unified)
    with patch('api.services.ai_model_probe._OPENER.open') as network:
        assert session.post(url, {}, format='json').status_code == 403
        session.get('/api/auth/csrf/')
        csrf = session.cookies['csrftoken'].value
        assert session.post(url, {}, format='json', HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN='https://evil.example').status_code == 403
        assert session.post(url, {}, format='json', HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_WORKSPACE_VIEWER=str(unified.owner.pk + 100)).status_code == 409
        with override_settings(AI_BYOK_ENABLED=False):
            assert unified.api.post(url, {}, format='json').status_code == 403
    network.assert_not_called()
