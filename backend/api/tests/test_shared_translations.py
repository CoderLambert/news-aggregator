"""Public output isolation, cross-user reuse, and fenced publication."""

from datetime import timedelta
from types import SimpleNamespace
import threading
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (Category, Source, News, ChatGPTSubscriptionConnection,
                        ChatGPTArticleTranslation, SharedArticleTranslation, SharedArticleTranslationTask)
from api.serializers import NewsDetailSerializer
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as jobs
from api.services import shared_translations as shared
from api.services.tts_service import resolve_tts_content

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def article():
    return News.objects.create(
        title='Public article', url='https://example.com/shared', publish_time=timezone.now(),
        source=Source.objects.create(name='Public source', url='https://example.com', language='en'),
        category=Category.objects.create(name='Tech', slug='tech'),
        full_content='# Public article\n\nOriginal English body.',
    )


def reader(name):
    user = get_user_model().objects.create_user(username=name)
    connection = ChatGPTSubscriptionConnection.objects.create(
        user=user, subject_hash=name, issuer='https://auth.example',
        issued_client_id=f'client-{name}', registration_key_hash=name,
        encrypted_access_token='opaque-access', encrypted_refresh_token='opaque-refresh',
        selected_model='selected-model', is_active=True,
    )
    return user, connection


def save(user, connection, article, text='完整的公共文章译文', lease=None):
    return subscription.save_completed_translation(
        user_id=user.pk, connection_id=connection.pk, news_id=article.pk,
        expected_generation=connection.generation, model_slug=connection.selected_model,
        text=text, source_digest=shared.source_hash(article.full_content), shared_lease=lease,
    )


def serialize(article, user=None):
    request = APIRequestFactory().get('/')
    request.user = user
    return NewsDetailSerializer(article, context={'request': request}).data


def body(response):
    return b''.join(response.streaming_content).decode()


def test_complete_private_result_has_independent_public_copy_and_reuses_without_credentials(article):
    first, connection = reader('first')
    save(first, connection, article)
    public = shared.get_shared_translation(article)
    assert public.content == '完整的公共文章译文'
    assert not any(f.name in {'user', 'connection', 'encrypted_access_token'} for f in public._meta.fields)
    assert serialize(article, first)['full_content_zh_scope'] == 'private'
    assert serialize(article)['full_content_zh_scope'] == 'shared'
    second, second_connection = reader('second')
    second_connection.needs_reauth = True
    second_connection.save()
    assert serialize(article, second)['full_content_zh'] == public.content
    client = APIClient()
    client.force_authenticate(second)
    with patch.object(jobs, 'start_or_get_job') as start:
        response = client.post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json')
        assert '"full_content_zh_scope": "shared"' in body(response)
    start.assert_not_called()
    assert not ChatGPTArticleTranslation.objects.filter(user=second).exists()
    first.delete()
    assert shared.get_shared_translation(article).content == public.content


def test_anonymous_can_read_completed_public_copy_without_model_call(article):
    user, connection = reader('owner')
    save(user, connection, article)
    with patch('api.views.get_clients', side_effect=AssertionError('must not check credentials')):
        result = body(APIClient().post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json'))
    assert '完整的公共文章译文' in result


def test_personal_retranslation_does_not_overwrite_public_and_survives_reload(article):
    owner, connection = reader('owner')
    save(owner, connection, article, '第一份共享译文')
    save(owner, connection, article, '用户重新生成的私有版本')
    assert serialize(article, owner)['full_content_zh'] == '用户重新生成的私有版本'
    assert serialize(article)['full_content_zh'] == '第一份共享译文'
    assert resolve_tts_content(article, owner, 'zh', 'full').content == '用户重新生成的私有版本'
    other, _ = reader('other')
    assert resolve_tts_content(article, other, 'zh', 'full').content == '第一份共享译文'


def test_historical_private_and_legacy_content_are_not_automatically_published(article):
    owner, connection = reader('owner')
    article.full_content_zh = '历史字段中的未知完整性文本'
    article.save()
    ChatGPTArticleTranslation.objects.create(
        user=owner, connection=connection, news=article,
        source_hash=shared.source_hash(article.full_content), model_slug='old-model',
        content='历史个人译文', completed_at=timezone.now(),
    )
    other, _ = reader('other')
    assert serialize(article, other)['full_content_zh'] == ''
    assert shared.get_shared_translation(article) is None


def test_source_changes_invalidate_both_scopes_and_prevent_late_publication(article):
    owner, connection = reader('owner')
    save(owner, connection, article)
    old_hash = shared.source_hash(article.full_content)
    article.full_content += '\n\nUpdated paragraph.'
    article.save()
    assert serialize(article, owner)['full_content_zh'] == ''
    assert shared.get_shared_translation(article) is None
    with pytest.raises(subscription.SubscriptionError, match='原文已更新'):
        subscription.save_completed_translation(
            user_id=owner.pk, connection_id=connection.pk, news_id=article.pk,
            expected_generation=0, model_slug='selected-model', text='迟到结果', source_digest=old_hash,
        )
    assert SharedArticleTranslation.objects.count() == 1


@pytest.mark.parametrize('text', ['', '   '])
def test_empty_result_is_not_saved_or_published(article, text):
    owner, connection = reader('owner')
    with pytest.raises(subscription.SubscriptionError, match='完整结果'):
        save(owner, connection, article, text)
    assert not SharedArticleTranslation.objects.exists()
    assert not ChatGPTArticleTranslation.objects.exists()


def test_account_fence_prevents_publication_after_disconnect(article):
    owner, connection = reader('owner')
    ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(is_active=False, generation=1)
    with pytest.raises(subscription.ConnectionChangedError):
        save(owner, connection, article)
    assert not SharedArticleTranslation.objects.exists()


def test_unique_claim_expiry_takeover_and_stale_token_cannot_publish(article):
    first = shared.claim_task(article)
    assert first is not None
    assert shared.claim_task(article) is None
    SharedArticleTranslationTask.objects.filter(pk=first.task_id).update(expires_at=timezone.now() - timedelta(seconds=1))
    replacement = shared.claim_task(article)
    assert replacement is not None and replacement.token != first.token
    with pytest.raises(shared.SharedTranslationError, match='已过期'):
        shared.publish_translation(news_id=article.pk, digest=shared.source_hash(article.full_content),
                                   text='旧任务结果', provider='chatgpt', lease=first)
    first.finish('failed')
    assert replacement.current().exists()
    shared.publish_translation(news_id=article.pk, digest=shared.source_hash(article.full_content),
                               text='接管后完整结果', provider='chatgpt', lease=replacement)
    assert shared.claim_task(article) is None


def test_failed_task_can_be_retried_and_waiter_does_not_receive_private_errors(article):
    lease = shared.claim_task(article)
    lease.finish('failed')
    assert '共享译文生成失败' in body(shared.waiting_response(article))
    assert shared.claim_task(article) is not None


def test_second_user_waits_for_one_model_call_without_receiving_private_chunks(article):
    first, first_connection = reader('first')
    second, _ = reader('second')
    emitted = threading.Event()
    release = threading.Event()

    def translate(**kwargs):
        kwargs['on_delta']('生成者的流式片段')
        emitted.set()
        assert release.wait(5)
        return '供所有读者复用的完整译文'

    a, b = APIClient(), APIClient()
    a.force_authenticate(first)
    b.force_authenticate(second)
    with patch.object(jobs, 'stream_full_translation', side_effect=translate) as model:
        response_a = a.post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json')
        try:
            assert emitted.wait(3)
            assert not SharedArticleTranslation.objects.exists()
            assert serialize(article, second)['full_translation_active'] is True
            response_b = b.post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json')
            iterator_b = iter(response_b.streaming_content)
            assert b'waiting_shared' in next(iterator_b)
            release.set()
            assert '供所有读者复用的完整译文' in b''.join(iterator_b).decode()
            assert '"full_content_zh_scope": "private"' in body(response_a)
        finally:
            release.set()
        model.assert_called_once()
    assert ChatGPTArticleTranslation.objects.filter(user=first).count() == 1
    assert ChatGPTArticleTranslation.objects.filter(user=second).count() == 0
    with jobs._jobs_lock:
        jobs._jobs.clear()


def test_generic_provider_partial_or_length_limited_response_is_not_complete():
    from api.services.llm_translator import _call_llm_stream
    chunk = SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content='仅部分译文'), finish_reason='length',
    )])
    client = Mock()
    client.chat.completions.create.return_value = iter([chunk])
    with patch('api.services.llm_translator.get_clients', return_value=[(client, 'model')]):
        iterator = _call_llm_stream('original')
        assert next(iterator) == '仅部分译文'
        with pytest.raises(ValueError, match='未完整完成'):
            list(iterator)
    assert client.chat.completions.create.call_count == 1


def test_force_request_uses_own_model_but_keeps_public_copy(article, monkeypatch):
    owner, connection = reader('owner')
    save(owner, connection, article, '第一份共享版本')
    other, _ = reader('other')
    client = APIClient()
    client.force_authenticate(other)
    # Focus this fake-only case on per-user/public persistence, not executor
    # scheduling. The shared-worker concurrency is exercised separately.
    monkeypatch.setattr(
        jobs, '_dispatch_task',
        lambda task_id, generation: jobs._run_persistent_task(task_id, generation),
    )
    with patch.object(jobs, 'stream_full_translation', return_value='第二位用户主动重翻的个人版本') as model:
        response = client.post(f'/api/news/{article.pk}/translate/', {'force': True}, format='json')
        assert '第二位用户主动重翻的个人版本' in body(response)
        model.assert_called_once()
    assert serialize(article, other)['full_content_zh'] == '第二位用户主动重翻的个人版本'
    assert shared.get_shared_translation(article).content == '第一份共享版本'


@pytest.mark.parametrize('successful', [True, False])
def test_generic_provider_only_publishes_whole_results_to_separate_table(article, successful):
    def stream(_):
        yield '流式片段'
        if not successful:
            raise ValueError('mock interrupted response')
        yield '，完整文章的结尾。'

    with (
        patch('api.views.get_clients', return_value=[(Mock(), 'model')]),
        patch('api.services.llm_translator.find_chinese_translation_link', return_value=None),
        patch('api.services.llm_translator._call_llm_stream', side_effect=stream),
    ):
        result = body(APIClient().post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json'))
    article.refresh_from_db()
    assert article.full_content_zh == ''
    if successful:
        assert 'event: complete' in result
        assert shared.get_shared_translation(article).content == '流式片段，完整文章的结尾。'
    else:
        assert '"error"' in result and 'event: complete' not in result
        assert shared.get_shared_translation(article) is None


def test_expired_queued_job_does_not_call_model(article):
    owner, connection = reader('owner')
    lease = shared.claim_task(article)
    SharedArticleTranslationTask.objects.filter(pk=lease.task_id).update(expires_at=timezone.now() - timedelta(seconds=1))
    job = jobs.ChatGPTTranslationJob(('queued',))
    with patch.object(jobs, 'stream_full_translation') as model:
        jobs._run_job(job, user_id=owner.pk, connection_id=connection.pk, news_id=article.pk,
                      source_digest=shared.source_hash(article.full_content), generation=0,
                      model_slug=connection.selected_model, article_markdown=article.full_content,
                      shared_lease=lease)
    model.assert_not_called()
    assert job.done and job.error
    assert not SharedArticleTranslation.objects.exists()


def test_source_change_during_translated_link_fetch_returns_actionable_sse_error(article):
    def fetched(_):
        News.objects.filter(pk=article.pk).update(full_content='New source body')
        return '旧原文对应的中文链接内容'

    with (
        patch('api.services.llm_translator.find_chinese_translation_link', return_value='https://example.com/zh'),
        patch('api.services.llm_translator.fetch_and_verify_chinese_content', side_effect=fetched),
    ):
        response = APIClient().post(f'/api/news/{article.pk}/translate/', {'force': False}, format='json')
    assert response.status_code == 200
    assert '原文已更新' in body(response)
    assert not SharedArticleTranslation.objects.exists()
