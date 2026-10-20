"""Production-isolated Django -> SDK -> actual pinned Proxy -> compatible HTTP."""
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import uuid
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_runtime import LocalProxy
from trusted_upstream import handler_type
from t04_django_localproxy import django_db_modify_db_settings

from api.ai_model_models import AICallAttempt, UserAIModelConfig
from api.models import News, Source, Category, ChatSession, ChatGPTArticleTranslation, ChatGPTTranslationTask
from api.services import ai_private_translation as translation
from api.tests.rss.reader_fixtures import public_legacy_article

BASE = '/api/me/ai/connections/'


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('auth_mode', ['none', 'api_key'])
def test_compatible_probe_chat_translation_tools_and_bad_terminal(tmp_path, settings, auth_mode):
    assert settings.DJANGO_ENV == 'production'
    owner = get_user_model().objects.create_user('unified-process-' + auth_mode)
    provider_key = 'synthetic-' + secrets.token_hex(24)
    Handler, records = handler_type({'owner': provider_key})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    item = {'profile_id': 'unified_fixture', 'version': 1, 'provider_id': 'ollama',
        'display_name': 'Synthetic compatible', 'protocol_family': 'chat_completions_v1',
        'api_base': url + '/v1', 'network_zone': 'same_host', 'allowed_ips': ['127.0.0.1'],
        'auth_modes': ['none', 'api_key'], 'allowed_user_ids': [owner.pk], 'enabled': True}
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([item]))
    try:
        with LocalProxy(os.environ['T00_PROXY_PYTHON'], url, trusted_profiles=[item]) as proxy, override_settings(
            ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False, PUBLIC_SITE_MODE='full',
            PUBLIC_AI_ENABLED=True, AI_BYOK_ENABLED=True, AI_BYOK_ENDPOINT_MANIFEST=str(manifest),
            AI_BYOK_GATEWAY_URL=proxy.url, AI_BYOK_GATEWAY_PROJECT_KEY=proxy.project_keys['tenant-a'],
            AI_BYOK_GATEWAY_PROJECT_KEY_FILE='',
            PROVIDER_CREDENTIAL_ENCRYPTION_KEY='synthetic-unified-process-encryption-material',
        ):
            api = APIClient()
            api.force_authenticate(owner)
            arguments = {'provider_id': 'ollama', 'endpoint_profile': 'unified_fixture', 'auth_mode': auth_mode,
                'display_name': 'Synthetic connection', 'request_id': str(uuid.uuid4())}
            if auth_mode == 'api_key':
                arguments['api_key'] = provider_key
            created = api.post(BASE, arguments, format='json')
            assert created.status_code == 201, created.content
            models_url = BASE + created.data['id'] + '/models/'
            created = api.post(models_url, {'model_id': 'org/model:cloud'}, format='json')
            assert created.status_code == 201
            model_id = created.data['id']
            assert records == []  # Saving settings did not infer anything.
            for kind in ('text', 'tools'):
                outcome = api.post(models_url + model_id + '/probe/', {'probe_kind': kind, 'revision': 1,
                    'request_id': str(uuid.uuid4())}, format='json')
                assert outcome.status_code == 200 and outcome.data['status'] == 'succeeded', outcome.content
            assert len(records) == 2
            source = Source.objects.create(name='Synthetic process publisher', url='https://publisher.example/', language='en')
            category = Category.objects.create(name='Unified process', slug='unified-process')
            article = public_legacy_article(News.objects.create(title='Synthetic process article',
                url='https://publisher.example/process', source=source, category=category,
                content='Synthetic summary', publish_time=timezone.now(), full_content_state='legacy',
                full_content='Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph.'))
            def ask():
                result = api.post(f'/api/news/{article.pk}/chat/', {'question': 'What happened?',
                    'model_config_id': model_id, 'billing_consent': True, 'turn_id': str(uuid.uuid4())}, format='json')
                assert result.status_code == 200, result.content
                return b''.join(result.streaming_content)
            wire = ask()
            assert b'"status": "complete"' in wire
            history = ChatSession.objects.get(user=owner, news=article)
            assert len([row for row in history.messages if row['role'] == 'assistant']) == 1
            with patch.object(translation, '_dispatch'), patch.object(translation, 'MAX_INPUT_CHARS', 30), \
                    patch.object(translation, 'T06_CHUNK_INPUT_CHARS', 30):
                started = api.post(f'/api/news/{article.pk}/byok-translation/', {'model_config_id': model_id,
                    'billing_consent': True, 'target_language': 'zh'}, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
                assert started.status_code == 202, started.content
                task = ChatGPTTranslationTask.objects.get(pk=started.data['task_id'])
                translation.run_translation(task.pk, task.generation)
            task.refresh_from_db()
            assert task.status == 'succeeded', task.error_code
            assert ChatGPTArticleTranslation.objects.filter(user=owner, news=article).count() == 1
            from api.services.research.byok_execution import capture_snapshot, call_model_once
            payload = capture_snapshot(owner, model_id)
            response = call_model_once(payload, owner_id=owner.pk, messages=[{'role': 'user', 'content': 'synthetic'}],
                tools=[{'type': 'function', 'function': {'name': 'byok_probe', 'parameters': {'type': 'object'}}}],
                execution_guard=lambda: None)
            assert response.choices[0].finish_reason == 'tool_calls'
            assert all(row['auth_label'] == ('owner' if auth_mode == 'api_key' else 'none') for row in records)
            before = len(records)
            Handler.stream_override = 'nh-eof'
            wire = ask()
            assert b'"status": "complete"' not in wire
            assert len(records) == before + 1
            history.refresh_from_db()
            assert len([row for row in history.messages if row['role'] == 'assistant']) == 1
            assert AICallAttempt.objects.filter(user=owner, status='unknown').exists()
            other = get_user_model().objects.create_user('unified-process-other-' + auth_mode)
            api.force_authenticate(other)
            assert api.get('/api/me/ai/usage/').data['attempts'] == []
            assert UserAIModelConfig.objects.get(pk=model_id).capability_results['tools']['status'] == 'supported'
        assert proxy.cleanup_complete
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
