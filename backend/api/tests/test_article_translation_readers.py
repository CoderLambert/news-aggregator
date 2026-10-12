from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (
    Category,
    ChatGPTTranslationTask,
    News,
    SharedArticleTranslation,
    Source,
    UserAIConnection,
)
from api.serializers import NewsDetailSerializer
from api.services.article_translations import (
    TranslationResultNotFound,
    get_byok_result,
    resolve_article_translation,
)
from api.services.shared_translations import source_hash
from api.services.tts_service import TTSContentUnavailable, resolve_tts_content

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def article():
    return News.objects.create(
        title='Reader contract',
        title_zh='读取契约',
        content='Short summary',
        content_zh='中文摘要',
        full_content='# Source\n\nCurrent English article.',
        publish_time=timezone.now(),
        source=Source.objects.create(name='Reader source', url='https://reader.example.test', language='en'),
        category=Category.objects.create(name='Reader tests', slug='reader-tests'),
        url='https://reader.example.test/article',
    )


def make_private_result(user, article, text, *, source=None, model='deepseek-flash'):
    connection = UserAIConnection.objects.create(
        user=user,
        provider_id='deepseek',
        endpoint_profile='deepseek_default',
        display_name=f'{user.username} test connection',
    )
    source = article.full_content if source is None else source
    task = ChatGPTTranslationTask.objects.create(
        user=user,
        ai_connection=connection,
        news=article,
        source_hash=source_hash(source),
        model_slug=model,
        idempotency_key=str(uuid.uuid4()),
        status='succeeded',
        finished_at=timezone.now(),
    )
    task.result = {
        'full_content_zh': text,
        'full_content_zh_source': 'byok',
        'full_content_zh_scope': 'private',
        'full_content_zh_fetched_at': task.finished_at.isoformat(),
        'model_source': {'provider': 'DeepSeek', 'model': model},
        'result_id': str(task.pk),
        'source_hash': task.source_hash,
    }
    task.save(update_fields=['result'])
    return connection, task


def serialize(article, user):
    request = APIRequestFactory().get('/')
    request.user = user
    return NewsDetailSerializer(article, context={'request': request}).data


def test_detail_chat_and_tts_resolve_one_private_result_without_translation_dispatch(article, monkeypatch, tmp_path):
    owner = User.objects.create_user(username='reader-owner')
    _connection, task = make_private_result(owner, article, '# 私人全文译文\n\n与当前原文匹配。')
    result_id = str(task.pk)

    detail = serialize(article, owner)
    assert detail['full_content_zh'] == task.result['full_content_zh']
    assert detail['full_content_zh_scope'] == 'private'
    assert detail['full_content_zh_source'] == 'byok'
    assert detail['full_content_zh_result_id'] == result_id
    assert detail['full_content_zh_current_match'] is True
    assert detail['full_content_zh_model_source'] == {'provider': 'DeepSeek', 'model': 'deepseek-flash'}

    client = APIClient()
    client.force_authenticate(owner)
    observed = {}

    def fake_chat(messages, **_kwargs):
        observed['messages'] = messages
        return iter(['已读取'])

    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    monkeypatch.setattr('api.views.stream_chat', fake_chat)
    with patch('api.services.chatgpt_subscription_jobs.stream_byok_translation', side_effect=AssertionError('GET readers must not translate')):
        chat = client.post(
            f'/api/news/{article.pk}/chat/',
            {'question': '总结一下', 'translation_result_id': result_id},
            format='json',
        )
        assert chat.status_code == 200
        b''.join(chat.streaming_content)
        assert task.result['full_content_zh'] in observed['messages'][0]['content']
        assert ChatGPTTranslationTask.objects.count() == 1

        class FakeCommunicate:
            def __init__(self, text, voice):
                observed['speech'] = text
                observed['voice'] = voice

            async def stream(self):
                yield {'type': 'audio', 'data': b'a' * 256}

        monkeypatch.setitem(sys.modules, 'edge_tts', SimpleNamespace(Communicate=FakeCommunicate))
        monkeypatch.setattr('api.services.tts_service.TTS_CACHE_DIR', str(tmp_path))
        tts = client.get(f'/api/news/{article.pk}/tts/?language=zh&scope=full&result_id={result_id}')
        assert tts.status_code == 200
        assert tts['Cache-Control'].startswith('private')
        b''.join(tts.streaming_content)
        assert '私人全文译文' in observed['speech']
        assert ChatGPTTranslationTask.objects.count() == 1

    resolved = resolve_tts_content(article, owner, 'zh', 'full', result_id=result_id)
    assert resolved.content == detail['full_content_zh']
    assert resolved.namespace == f'byok:{owner.pk}:result:{result_id}'


def test_private_results_are_owner_scoped_and_take_priority_over_public(article):
    owner_a = User.objects.create_user(username='reader-a')
    owner_b = User.objects.create_user(username='reader-b')
    _connection_a, task_a = make_private_result(owner_a, article, 'A 的个人结果')
    _connection_b, task_b = make_private_result(owner_b, article, 'B 的个人结果')
    SharedArticleTranslation.objects.create(
        news=article,
        source_hash=source_hash(article.full_content),
        target_language='zh-CN',
        translation_version='article-v1',
        content='公共结果',
        provider='test',
        model_slug='test-model',
        completed_at=timezone.now(),
    )

    assert resolve_article_translation(article, owner_a).content == 'A 的个人结果'
    assert resolve_article_translation(article, owner_b).content == 'B 的个人结果'
    assert resolve_article_translation(article).content == '公共结果'
    assert resolve_tts_content(article, owner_a, 'zh', 'full', str(task_a.pk)).content == 'A 的个人结果'
    assert resolve_tts_content(article, owner_b, 'zh', 'full', str(task_b.pk)).content == 'B 的个人结果'
    assert resolve_tts_content(article, owner_a, 'zh', 'full', str(task_a.pk)).namespace != resolve_tts_content(
        article, owner_b, 'zh', 'full', str(task_b.pk),
    ).namespace
    with pytest.raises(TranslationResultNotFound):
        get_byok_result(owner_b, article, str(task_a.pk))
    with pytest.raises(TTSContentUnavailable) as error:
        resolve_tts_content(article, owner_b, 'zh', 'full', str(task_a.pk))
    assert error.value.code == 'translation_result_not_found'

    client = APIClient()
    client.force_authenticate(owner_b)
    tts = client.get(f'/api/news/{article.pk}/tts/?language=zh&scope=full&result_id={task_a.pk}')
    assert tts.status_code == 404
    assert tts['Cache-Control'] == 'no-store'


def test_chat_rejects_another_users_result_before_opening_a_chat_turn(article, monkeypatch):
    owner = User.objects.create_user(username='reader-chat-owner')
    other = User.objects.create_user(username='reader-chat-other')
    _connection, task = make_private_result(owner, article, '不得用于他人聊天的译文')
    client = APIClient()
    client.force_authenticate(other)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: pytest.fail('invalid result must fail before fetch'))
    monkeypatch.setattr('api.views.stream_chat', lambda *_args, **_kwargs: pytest.fail('invalid result must fail before model dispatch'))

    response = client.post(
        f'/api/news/{article.pk}/chat/',
        {'question': '提问', 'translation_result_id': str(task.pk)},
        format='json',
    )

    assert response.status_code == 404
    assert response['Cache-Control'] == 'no-store'


def test_source_changes_keep_saved_result_readable_but_mark_it_stale(article):
    owner = User.objects.create_user(username='reader-stale')
    connection, task = make_private_result(owner, article, '旧原文对应的译文')
    old_hash = task.source_hash
    article.full_content += '\n\nA new source paragraph.'
    article.save(update_fields=['full_content'])

    detail = serialize(article, owner)
    assert detail['full_content_zh'] == ''
    assert detail['full_content_zh_result_id'] is None
    assert detail['full_content_zh_stale_result_id'] == str(task.pk)
    assert detail['full_content_zh_stale_model_source'] == {'provider': 'DeepSeek', 'model': 'deepseek-flash'}

    client = APIClient()
    client.force_authenticate(owner)
    connection.is_deleted = True
    connection.credential_ciphertext = ''
    connection.save(update_fields=['is_deleted', 'credential_ciphertext'])
    response = client.get(f'/api/ai/translation/results/{task.pk}/')
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    assert response.json()['full_content_zh'] == '旧原文对应的译文'
    assert response.json()['source_hash'] == old_hash
    assert response.json()['current_match'] is False


def test_private_result_endpoint_rejects_other_owner_and_does_not_require_enabled_key(article, settings):
    owner = User.objects.create_user(username='reader-result-owner')
    other = User.objects.create_user(username='reader-result-other')
    connection, task = make_private_result(owner, article, '只属于所有者的译文')
    connection.is_deleted = True
    connection.credential_ciphertext = ''
    connection.save(update_fields=['is_deleted', 'credential_ciphertext'])
    settings.AI_BYOK_ENABLED = False

    owner_client = APIClient()
    owner_client.force_authenticate(owner)
    response = owner_client.get(f'/api/ai/translation/results/{task.pk}/')
    assert response.status_code == 200
    assert response.json()['result_id'] == str(task.pk)

    other_client = APIClient()
    other_client.force_authenticate(other)
    denied = other_client.get(f'/api/ai/translation/results/{task.pk}/')
    assert denied.status_code == 404
    assert denied['Cache-Control'] == 'no-store'


def test_saved_result_reader_keeps_older_row_id_links_readable(article):
    owner = User.objects.create_user(username='reader-legacy-id')
    _connection, task = make_private_result(owner, article, '旧客户端保存的结果')
    task.result['result_id'] = '317'
    task.save(update_fields=['result'])

    client = APIClient()
    client.force_authenticate(owner)
    response = client.get('/api/ai/translation/results/317/')

    assert response.status_code == 200
    assert response.json()['full_content_zh'] == '旧客户端保存的结果'
    assert response.json()['result_id'] == str(task.pk)
