"""T14 stored-context, translation version and revocation boundaries."""
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.http import Http404
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from api.models import News, LegacyTranslationSnapshot, SharedArticleTranslation, ChannelSubscription
from api.rss.access import get_stored_article
from api.rss.models import SourcePublication
from api.services import shared_translations as shared
from api.services.stored_readers import current_translation, require_current, StoredContentChanged
from api.services.tts_service import resolve_tts_content, TTSContentUnavailable, build_cache_variant
from api.services.research.tools import _tool_fetch_article, _tool_fetch_webpage, execute_tool
from api.serializers import NewsDetailSerializer
from api.tests.rss.test_access_contract import world, api_client

pytestmark = pytest.mark.django_db


def archive(news, field, source, text, origin='legacy'):
    return LegacyTranslationSnapshot.objects.create(news=news, field=field, source_text=source,
        source_hash=sha256(source.encode()).hexdigest(), translated_text=text,
        translation_hash=sha256(text.encode()).hexdigest(), origin=origin)


def test_available_snapshot_metadata_and_summary_are_not_full(world):
    a, _, make = world
    source, news = make('available', subscriber=a, state='available')
    result = _tool_fetch_article(news.pk, user=a)
    assert result['source_scope'] == 'full' and result['content_completeness'] == 'unknown'
    assert result['canonical_hash'] == sha256(news.full_content.encode()).hexdigest()
    assert result['full_content_revision'] == news.full_content_revision
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    result = _tool_fetch_article(news.pk, user=a)
    assert result['source_scope'] == 'summary' and result['content'] == news.content
    with pytest.raises(TTSContentUnavailable):
        resolve_tts_content(news, a, 'original', 'full')


def test_research_no_provider_and_user_id_cannot_be_injected(world, monkeypatch):
    a, b, make = world
    _, news = make('personal', subscriber=a)
    monkeypatch.setattr('api.services.article_content.request_full_content', lambda *a, **k: pytest.fail('implicit fetch'))
    assert _tool_fetch_article(news.pk, user=b).get('error')
    assert _tool_fetch_webpage(news.url, user=b)['capability'] == 'stored_articles_only'
    assert _tool_fetch_webpage('https://new.example/not-indexed', user=a)['content'] == ''
    assert _tool_fetch_webpage(news.url, user=a)['content'] == news.full_content
    session = SimpleNamespace(user=b)
    assert execute_tool('fetch_article', {'article_id': news.pk, 'user': a}, session=session).get('error')


def test_search_web_still_uses_explicit_search_handler(monkeypatch):
    from api.services.research import tools
    call = Mock(return_value={'results': [{'title': 'Result', 'url': 'https://example.com', 'snippet': 'search summary'}]})
    monkeypatch.setattr(tools, '_tool_search_web', call)
    assert execute_tool('search_web', {'query': 'topic'})['results'][0]['snippet'] == 'search summary'
    call.assert_called_once_with(query='topic')


def test_translation_uses_new_snapshot_not_stale_news(world):
    a, _, make = world
    source, news = make('snapshot', subscriber=a)
    source.language = 'en'; source.save(update_fields=['language'])
    shared.publish_translation(news_id=news.pk, digest=shared.source_hash(news.full_content), text='old translation', provider='llm')
    News.objects.filter(pk=news.pk).update(full_content='new body', title='new title', full_content_revision=2)
    stored = get_stored_article(a, news.pk)
    shared.publish_translation(news_id=news.pk, digest=stored.canonical_hash, text='new translation', provider='llm')
    request = APIRequestFactory().get('/'); request.user = a
    data = NewsDetailSerializer(news, context={'request': request}).data
    assert data['title'] == 'new title' and data['full_content'] == 'new body'
    assert data['full_content_revision'] == 2
    assert data['full_content_zh'] == 'new translation'
    spoken = resolve_tts_content(news, a, 'zh', 'full')
    assert spoken.title == 'new title' and spoken.content == 'new translation'


def test_legacy_exact_hash_only_and_history_remains(world):
    a, _, make = world
    _, news = make('legacy', subscriber=a)
    news.full_content_zh = 'unbound'; news.save(update_fields=['full_content_zh'])
    stored = get_stored_article(a, news.pk)
    assert current_translation(a, stored) == (None, None)
    old = archive(news, 'full_content', 'different old body', 'old historical translation')
    assert current_translation(a, stored) == (None, None)
    archive(news, 'full_content', news.full_content, 'matched historical translation')
    record, scope = current_translation(a, stored)
    assert record.content == 'matched historical translation' and scope == 'legacy'
    assert LegacyTranslationSnapshot.objects.filter(pk=old.pk).exists()


def test_completed_old_hash_is_history_never_current(world):
    a, _, make = world
    _, news = make('late', subscriber=a)
    old = get_stored_article(a, news.pk)
    News.objects.filter(pk=news.pk).update(full_content='new version', full_content_revision=2)
    with pytest.raises(shared.SharedTranslationError):
        shared.publish_translation(news_id=news.pk, digest=old.canonical_hash, text='old result', provider='llm')
    assert SharedArticleTranslation.objects.filter(news=news, source_hash=old.canonical_hash).exists()
    assert shared.get_shared_translation(news, a) is None
    with pytest.raises(StoredContentChanged):
        require_current(a, old, full=True)


def test_waiting_and_completed_cache_reauthorize_before_bytes(world):
    a, _, make = world
    source, news = make('revoke', subscriber=a)
    stored = get_stored_article(a, news.pk)
    record = shared.publish_translation(news_id=news.pk, digest=stored.canonical_hash, text='secret', provider='llm')
    response = shared.waiting_response(news, a, stored=stored)
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    assert b'secret' not in b''.join(response.streaming_content)
    response = shared.completed_response(record, user=a, stored=stored)
    payload = b''.join(response.streaming_content)
    assert b'error' in payload and b'secret' not in payload and b'full_content_zh' not in payload


def test_tts_cache_identity_and_subscription_revocation(world):
    a, b, make = world
    source, news = make('speech', subscriber=a)
    resolved = resolve_tts_content(news, a, 'original', 'full')
    original_key = build_cache_variant(resolved, 'full', 'voice', 'text')
    News.objects.filter(pk=news.pk).update(full_content_revision=2)
    changed = resolve_tts_content(news, a, 'original', 'full')
    assert build_cache_variant(changed, 'full', 'voice', 'text') != original_key
    ChannelSubscription.objects.filter(user=a, source=source).delete()
    with pytest.raises(Http404):
        resolve_tts_content(news, a, 'original', 'full')
    with pytest.raises(Http404):
        resolve_tts_content(news, b, 'original', 'full')


def test_translation_has_no_chinese_link_helpers():
    from api.services import llm_translator
    assert not hasattr(llm_translator, 'find_chinese_translation_link')
    assert not hasattr(llm_translator, 'fetch_and_verify_chinese_content')


def test_shared_job_key_is_actor_and_hash_scoped(monkeypatch):
    from api.services import translation_jobs
    monkeypatch.setattr(translation_jobs, '_jobs', {(1, 5, 'old'): object(), (1, 6, 'new'): object()})
    assert translation_jobs.get_job(1, user_id=5, source_digest='old') is not None
    assert translation_jobs.get_job(1, user_id=6, source_digest='old') is None
    assert translation_jobs.get_job(1, user_id=5, source_digest='new') is None


def test_snapshot_guard_provenance_change_same_hash(world):
    a, _, make = world
    _, news = make('provenance', subscriber=a)
    stored = get_stored_article(a, news.pk)
    News.objects.filter(pk=news.pk).update(full_content_provenance={'legacy_note': 'changed'})
    with pytest.raises(StoredContentChanged):
        require_current(a, stored)


def test_private_versions_preserved_and_connection_switch_rechecked(world):
    from api.tests.test_shared_translations import reader, save
    from api.models import ChatGPTArticleTranslation
    a, _, make = world
    _, news = make('versions', 'public')
    user, connection = reader('private-versions')
    save(user, connection, news, 'first shared result')
    save(user, connection, news, 'private revision one')
    old_hash = shared.source_hash(news.full_content)
    news.full_content = 'new version'; news.full_content_revision = 2
    news.save(update_fields=['full_content', 'full_content_revision'])
    save(user, connection, news, 'new shared result')
    save(user, connection, news, 'private revision two')
    assert ChatGPTArticleTranslation.objects.get(user=user, news=news, source_hash=old_hash).content == 'private revision one'
    stored = get_stored_article(user, news.pk)
    assert current_translation(user, stored)[0].content == 'private revision two'
    record = ChatGPTArticleTranslation.objects.get(user=user, news=news, source_hash=stored.canonical_hash)
    response = shared.completed_response(record, 'private', user=user, stored=stored)
    connection.is_active = False; connection.save(update_fields=['is_active'])
    payload = b''.join(response.streaming_content)
    assert b'error' in payload and b'private revision two' not in payload and b'full_content_zh' not in payload
    assert current_translation(user, stored)[0].content == 'new shared result'


def test_exact_legacy_title_summary_display_and_speech(world):
    a, _, make = world
    source, news = make('summary-history', subscriber=a)
    source.language = 'en'; source.save(update_fields=['language'])
    news.title_zh = 'unbound title'; news.content_zh = 'unbound summary'
    news.save(update_fields=['title_zh', 'content_zh'])
    client = api_client(a)
    assert client.get(f'/api/news/{news.pk}/').data['title_zh'] == ''
    archive(news, 'title', news.title, 'verified title')
    archive(news, 'content', news.content, 'verified summary')
    data = client.get(f'/api/news/{news.pk}/').data
    assert data['title_zh'] == 'verified title' and data['content_zh'] == 'verified summary'
    speech = resolve_tts_content(news, a, 'zh', 'summary')
    assert speech.title == 'verified title' and speech.content == 'verified summary'


def test_research_history_replay_denied_after_policy_change(world):
    from api.models import ResearchSession, ResearchSearchResult
    from api.services.research.access import require_session_evidence
    a, _, make = world
    source, news = make('research-history', subscriber=a)
    session = ResearchSession.objects.create(user=a)
    result = _tool_fetch_article(news.pk, user=a)
    ResearchSearchResult.objects.create(session=session, tool_name='fetch_article', result_type='article', result_data=result)
    require_session_evidence(session, a)
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    with pytest.raises(Http404):
        require_session_evidence(session, a)
    assert session.search_results.count() == 1


def test_research_search_result_replay_is_snapshot_and_policy_bound(world):
    import json
    from api.models import ResearchSession, ResearchSearchResult
    from api.services.research.access import require_session_evidence, result_is_current
    from api.services.research.tools import _serialize_news_list

    a, _, make = world
    source, news = make('research-search-snapshot', subscriber=a, state='available')

    def persist(result, tool_name='search_news', *, include_envelope=True, include_result=True):
        messages = []
        if include_envelope:
            messages = [
                {'role': 'assistant', 'tool_calls': [
                    {'id': 'search-1', 'function': {'name': tool_name, 'arguments': '{}'}}
                ]},
                {'role': 'tool', 'tool_call_id': 'search-1', 'content': json.dumps(result)},
            ]
        session = ResearchSession.objects.create(user=a, messages=messages)
        if include_result:
            ResearchSearchResult.objects.create(session=session, tool_name=tool_name,
                result_type='news', result_data=result)
        return session

    original = {'articles': _serialize_news_list([news], a)}
    article = original['articles'][0]
    assert article['source_scope'] == 'full'
    assert article['policy_versions']

    # Exercise the persisted model envelope and DB result row independently.
    envelope_session = persist(original, include_result=False)
    row_session = persist(original, include_envelope=False)
    require_session_evidence(envelope_session, a)
    require_session_evidence(row_session, a)

    # analyze_topic duplicates article titles into a timeline. Model a truncated
    # articles list so the only retained evidence for this ID is its timeline event.
    metadata_fields = ('context_scope', 'full_content_revision', 'canonical_hash',
        'content_completeness', 'provenance_hash', 'source_scope', 'policy_versions')
    event = {key: article[key] for key in metadata_fields}
    event.update(title=article['title'], article_id=article['id'], source=article['source'])
    topic = {'articles': [], 'timeline': [
        {'date': '2026-10-19', 'events': [event]},
    ]}
    topic_session = persist(topic, 'analyze_topic')
    require_session_evidence(topic_session, a)

    # The same article remains authorized, but a new revision must invalidate its
    # previously persisted title/snippet and tool envelope before model replay.
    news.content = 'revised summary'
    news.full_content = 'revised body'
    news.full_content_revision += 1
    news.save(update_fields=['content', 'full_content', 'full_content_revision'])
    assert get_stored_article(a, news.pk).scope == 'full'
    for session in (envelope_session, row_session, topic_session):
        with pytest.raises(Http404):
            require_session_evidence(session, a)

    # Old results without a snapshot cannot be treated as current merely because
    # their article ID is still authorized.
    legacy = {'articles': [{'id': news.pk, 'title': news.title,
        'url': news.url, 'snippet': news.content}]}
    assert result_is_current(a, 'search_news', legacy) is False

    fresh = {'articles': _serialize_news_list([news], a)}
    policy_session = persist(fresh, include_envelope=False)
    require_session_evidence(policy_session, a)

    # Policy version is part of the read snapshot even when scope and bytes stay
    # unchanged; changing it invalidates a previously captured search result.
    SourcePublication.objects.filter(source=source).update(policy_version=2)
    with pytest.raises(Http404):
        require_session_evidence(policy_session, a)


def test_private_task_poll_hides_progress_after_policy_revocation(world):
    from api.models import ChatGPTTranslationTask
    from api.tests.test_shared_translations import reader
    from api.services.chatgpt_subscription_jobs import get_task
    a, _, make = world
    source, news = make('private-task', 'public')
    user, connection = reader('task-owner')
    task = ChatGPTTranslationTask.objects.create(user=user, connection=connection, news=news,
        source_hash=shared.source_hash(news.full_content), connection_generation=connection.generation,
        model_slug=connection.selected_model, status='succeeded', progress='private secret', result={'secret': 'complete'})
    assert get_task(task.pk, user_id=user.pk).progress == 'private secret'
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    assert get_task(task.pk, user_id=user.pk) is None
    assert ChatGPTTranslationTask.objects.get(pk=task.pk).progress == 'private secret'


def test_chat_stream_stops_after_policy_revocation(world, monkeypatch):
    a, _, make = world
    source, news = make('stream', subscriber=a)
    # Only a synthetic, explicitly injected consumer client is allowed here.
    # The test checks revocation in the SSE path, never site Key selection.
    monkeypatch.setattr('api.services.ai_execution.personal_clients_for_user',
                        lambda _user: [(object(), 'synthetic-model')])
    monkeypatch.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda user: None)
    def chunks(*args, **kwargs):
        yield 'allowed first chunk'
        SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
        yield 'forbidden late chunk'
    monkeypatch.setattr('api.views.stream_chat', chunks)
    response = api_client(a).post(f'/api/news/{news.pk}/chat/', {'question': 'explain'}, format='json')
    wire = b''.join(response.streaming_content).decode()
    assert 'allowed first chunk' in wire and 'forbidden late chunk' not in wire
    assert '"status": "failed"' in wire
    assert not any(m['role'] == 'assistant' for m in api_client(a).get(f'/api/news/{news.pk}/chat/').data['messages'])


def test_empty_legacy_owner_keeps_authorized_task_status(world):
    a, _, make = world
    _, news = make('empty-queued', subscriber=a)
    news.body_owner_source = None; news.full_content = ''; news.full_content_state = 'missing'
    news.full_content_fetch_status = 'queued'; news.full_content_retry_count = 1
    news.save()
    data = api_client(a).get(f'/api/news/{news.pk}/').data
    assert not data['has_full_content'] and data['full_content'] == ''
    assert data['full_content_fetch_status'] == 'queued' and data['full_content_retry_count'] == 1


def test_unbound_translation_not_searchable_but_exact_archived_translation_is(world):
    a, _, make = world
    _, news = make('keyword-version', subscriber=a)
    news.title_zh = 'old-private-translation-marker'; news.save(update_fields=['title_zh'])
    client = api_client(a)
    assert client.get('/api/news/', {'search': 'old-private-translation-marker'}).data['count'] == 0
    archive(news, 'title', news.title, 'current-translation-marker')
    assert client.get('/api/news/', {'search': 'current-translation-marker'}).data['count'] == 1


def test_research_keyword_retains_hash_bound_chinese_search(world, monkeypatch):
    import sys
    from api.services.research.tools import _tool_search_news
    a, _, make = world
    _, news = make('translated-search', subscriber=a)
    archive(news, 'title', news.title, '中文搜索证据')
    monkeypatch.setitem(sys.modules, 'api.services.vector_store', SimpleNamespace(VectorStoreService=lambda: None))
    result = _tool_search_news('中文搜索证据', mode='keyword', user=a)
    assert [row['id'] for row in result['articles']] == [news.pk]
    News.objects.filter(pk=news.pk).update(title='different source title')
    assert _tool_search_news('中文搜索证据', mode='keyword', user=a)['articles'] == []


def test_snapshot_guard_policy_version_change_with_identical_readable_bytes(world):
    from django.db.models import F
    a, _, make = world
    source, news = make('policy-version-only', subscriber=a)
    stored = get_stored_article(a, news.pk)
    assert require_current(a, stored) == stored
    SourcePublication.objects.filter(source=source).update(policy_version=F('policy_version') + 1)
    current = get_stored_article(a, news.pk)
    assert current.scope == stored.scope
    assert current.canonical_hash == stored.canonical_hash
    assert current.markdown == stored.markdown
    assert current.policy_versions != stored.policy_versions
    with pytest.raises(StoredContentChanged):
        require_current(a, stored)
