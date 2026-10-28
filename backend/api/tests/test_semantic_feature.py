"""Semantic search is opt-in; disabled paths never reach vector/queue work."""
import io
from unittest.mock import patch

import pytest
from django.core.management import call_command, CommandError
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory

from api.views import NewsListView
from api.tests.test_public_policy import news_obj  # reuse public synthetic article


@pytest.fixture(autouse=True)
def full_site(settings):
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.SEMANTIC_SEARCH_ENABLED = False


@pytest.mark.django_db
@pytest.mark.parametrize('mode', ['semantic', 'hybrid'])
def test_disabled_http_and_direct_view_never_execute_semantics(news_obj, mode):
    with patch.object(NewsListView, '_semantic_search', return_value=Response({'count': 0})) as semantic, \
         patch.object(NewsListView, '_hybrid_search', return_value=Response({'count': 0})) as hybrid:
        response = APIClient().get('/api/news/', {'search': 'PolicyKeyword', 'mode': mode})
        assert response.status_code == 403
        assert response.json()['error_code'] == 'semantic_search_disabled'
        direct = NewsListView.as_view()(APIRequestFactory().get('/api/news/', {'search': 'PolicyKeyword', 'mode': mode}))
        assert direct.status_code == 403
        semantic.assert_not_called()
        hybrid.assert_not_called()


@pytest.mark.django_db
def test_keyword_and_other_capabilities_survive(news_obj):
    with patch('api.services.embedding.EmbeddingService.encode') as encode:
        response = APIClient().get('/api/news/', {'search': 'PolicyKeyword'})
        assert response.status_code == 200
        assert [item['id'] for item in response.json()['results']] == [news_obj.pk]
        features = APIClient().get('/api/capabilities/').json()['features']
        assert features['keyword_search']['enabled'] is True
        assert features['semantic_search'] == {'enabled': False, 'reason': 'semantic_search_disabled'}
        assert features['chat']['enabled'] is True
        encode.assert_not_called()


@pytest.mark.parametrize('flag,ai,mode,expected', [(False, True, 'full', False), (True, True, 'full', True),
    (True, False, 'full', False), (True, True, 'read_only', False), ('1', True, 'full', False)])
def test_effective_switch(settings, flag, ai, mode, expected):
    from api.services.semantic_search import semantic_search_enabled
    settings.SEMANTIC_SEARCH_ENABLED = flag
    settings.PUBLIC_AI_ENABLED = ai
    settings.PUBLIC_SITE_MODE = mode
    assert semantic_search_enabled() is expected


def test_unknown_switch_fails_closed(settings):
    from api.services.semantic_search import semantic_search_enabled
    del settings.SEMANTIC_SEARCH_ENABLED
    assert semantic_search_enabled() is False


def test_disabled_embedding_and_preload_have_no_side_effects():
    from api.services.embedding import EmbeddingService
    from api.services.semantic_search import SemanticSearchDisabled
    with patch('api.services.embedding.threading.Thread') as thread:
        EmbeddingService.preload()
        thread.assert_not_called()
    with pytest.raises(SemanticSearchDisabled):
        EmbeddingService().encode('synthetic text')
    with pytest.raises(SemanticSearchDisabled):
        EmbeddingService().encode_batch(['synthetic text'])


def test_disabled_startup_does_not_preload():
    from api.apps import ApiConfig
    with patch('api.services.embedding.EmbeddingService.preload') as preload, \
         patch.dict('os.environ', {}, clear=True), \
         patch('api.apps.sys', argv=['manage.py', 'runserver'], modules={}):
        ApiConfig('api', __import__('api')).ready()
        preload.assert_not_called()


def test_disabled_vector_reads_writes_do_not_open_storage():
    from api.services.vector_store import VectorStoreService
    from api.services.semantic_search import SemanticSearchDisabled
    service = VectorStoreService()
    with patch.object(VectorStoreService, 'get_collection') as collection, \
         patch('api.services.vector_store.EmbeddingService') as embedding:
        for operation in (lambda: service.search('query'), lambda: service.add_news(1, 'text'),
                          lambda: service.add_news_batch([1], ['text']), lambda: service.count()):
            with pytest.raises(SemanticSearchDisabled):
                operation()
        collection.assert_not_called()
        embedding.assert_not_called()


def test_disabled_queue_schedule_claim_and_sync_do_not_access_database():
    from api.services.search_index_control import queue_search_index_run, schedule_due_index_run, claim_next_index_run
    from api.services.search_index import synchronize_search_index
    from api.services.semantic_search import SemanticSearchDisabled
    # No django_db marker: any query/transaction on these paths fails the test.
    assert queue_search_index_run(trigger='manual', mode='rebuild') == (None, False)
    assert schedule_due_index_run() is None
    assert claim_next_index_run('synthetic-worker') is None
    with pytest.raises(SemanticSearchDisabled):
        synchronize_search_index('not-a-real-run')


@pytest.mark.parametrize('command', ['sync_embeddings', 'backfill_embeddings'])
def test_disabled_management_commands_do_not_recover_or_delete_candidates(command):
    with patch('api.management.commands.sync_embeddings.acquire_search_index_execution_lock') as lock:
        with pytest.raises(CommandError, match='semantic_search_disabled'):
            call_command(command, stdout=io.StringIO())
        lock.assert_not_called()


def test_disabled_runtime_health_does_not_read_index_state():
    from api.services.runtime_health import _search_index_check
    assert _search_index_check() == {'enabled': False, 'ready': False, 'status': 'disabled', 'code': ''}


@pytest.mark.django_db
def test_disabled_existing_queue_and_index_configuration_are_preserved(settings):
    from api.models import SearchIndexSettings, SearchIndexRun
    from api.services.search_index_control import queue_search_index_run, schedule_due_index_run, claim_next_index_run
    SearchIndexSettings.objects.create(pk=1, enabled=True, active_collection='synthetic-existing-index')
    run = SearchIndexRun.objects.create(trigger='manual', mode='rebuild')
    before = (list(SearchIndexSettings.objects.values()), list(SearchIndexRun.objects.values()))
    assert queue_search_index_run(trigger='startup') == (None, False)
    assert schedule_due_index_run() is None
    assert claim_next_index_run('worker') is None
    call_command('embedding_worker', once=True, stdout=io.StringIO())
    assert (list(SearchIndexSettings.objects.values()), list(SearchIndexRun.objects.values())) == before
    settings.SEMANTIC_SEARCH_ENABLED = True
    existing, created = queue_search_index_run(trigger='manual')
    assert existing.pk == run.pk and not created
    assert claim_next_index_run('worker').pk == run.pk


def test_enabled_startup_still_preloads(settings):
    from api.apps import ApiConfig
    settings.SEMANTIC_SEARCH_ENABLED = True
    with patch('api.services.embedding.EmbeddingService.preload') as preload, \
         patch.dict('os.environ', {}, clear=True), \
         patch('api.apps.sys', argv=['manage.py', 'runserver'], modules={}):
        ApiConfig('api', __import__('api')).ready()
        preload.assert_called_once()


def test_disabled_worker_and_healthcheck_do_not_touch_state():
    with patch('api.management.commands.embedding_worker.acquire_search_index_execution_lock') as lock:
        output = io.StringIO()
        call_command('embedding_worker', once=True, stdout=output)
        assert 'disabled' in output.getvalue()
        call_command('embedding_healthcheck', stdout=output)
        lock.assert_not_called()


@pytest.mark.django_db
def test_admin_cannot_enqueue_or_audit_when_disabled(django_user_model):
    user = django_user_model.objects.create_superuser(username='synthetic-admin', password='synthetic-only')
    client = APIClient()
    client.force_authenticate(user=user)
    with patch('api.search_index_views.queue_search_index_run') as queue, \
         patch('api.search_index_views.dashboard_index_audit') as audit:
        for method, path, body in [('post', '/api/admin/search-index/runs/', {'mode': 'rebuild'}),
                                   ('patch', '/api/admin/search-index/settings/', {'enabled': True}),
                                   ('get', '/api/admin/search-index/dashboard/', {})]:
            response = getattr(client, method)(path, body, format='json')
            assert response.status_code == 403
            assert response.json()['code'] == 'semantic_search_disabled'
        queue.assert_not_called()
        audit.assert_not_called()


@pytest.mark.django_db
def test_research_keeps_keyword_search_without_vector_access(news_obj):
    from api.services.research.tools import _tool_search_news, _tool_analyze_topic
    with patch('api.services.vector_store.VectorStoreService') as vector:
        result = _tool_search_news('PolicyKeyword', mode='hybrid')
        assert result['mode'] == 'keyword'
        assert result['total'] == 1
        refused = _tool_search_news('PolicyKeyword', mode='semantic')
        assert refused['error_code'] == 'semantic_search_disabled'
        topic = _tool_analyze_topic('PolicyKeyword')
        assert len(topic['articles']) == 1
        vector.assert_not_called()
