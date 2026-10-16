"""Re-entry attaches only to the caller's current source-hash job."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from api.models import Category, Source, News
from api.serializers import NewsDetailSerializer
from api.services import translation_jobs, shared_translations
from api.tests.rss.reader_fixtures import public_legacy_article


@pytest.fixture
def case(db, client, monkeypatch):
    user = User.objects.create_user('translation-reader')
    client.force_login(user)
    news = public_legacy_article(News.objects.create(title='Sample', url='https://example.com/a',
        source=Source.objects.create(name='Live source', url='https://example.com', language='en'),
        category=Category.objects.create(name='Tech', slug='tech'), publish_time=timezone.now(),
        full_content='Stored English body', full_content_state='legacy'))
    monkeypatch.setattr(translation_jobs, '_jobs', {})
    request = APIRequestFactory().get('/'); request.user = user
    key = (news.pk, user.pk, shared_translations.source_hash(news.full_content))
    return news, user, request, key


def test_serializer_reports_only_current_actor_hash_job(case):
    news, user, request, key = case
    job = SimpleNamespace(done=False)
    translation_jobs._jobs[key] = job
    assert NewsDetailSerializer(news, context={'request': request}).data['full_translation_active']
    assert not NewsDetailSerializer(news).data['full_translation_active']
    job.done = True
    assert not NewsDetailSerializer(news, context={'request': request}).data['full_translation_active']


def test_attach_path_takes_priority_over_unbound_partial_snapshot(case, client):
    news, user, request, key = case
    news.full_content_zh = 'unbound partial'; news.save(update_fields=['full_content_zh'])
    class Job:
        done = False; error = None; text = ''
        def wait_for_update(self, *_args, **_kwargs):
            self.text = 'complete current translation'; self.done = True
            shared_translations.publish_translation(news_id=news.pk, digest=key[2], text=self.text, provider='llm')
    translation_jobs._jobs[key] = Job()
    with patch.object(translation_jobs, 'start_or_get_job', side_effect=AssertionError('duplicate model call')):
        response = client.post(f'/api/news/{news.pk}/translate/', {'force': False}, content_type='application/json')
        body = b''.join(response.streaming_content).decode()
    assert 'event: complete' in body and 'complete current translation' in body
    assert 'unbound partial' not in body


def test_finished_worker_falls_through_to_hash_bound_snapshot(case, client):
    news, _, _, key = case
    shared_translations.publish_translation(news_id=news.pk, digest=key[2], text='stored complete translation', provider='llm')
    with patch.object(translation_jobs, 'start_or_get_job', side_effect=AssertionError('duplicate model call')):
        response = client.post(f'/api/news/{news.pk}/translate/', {'force': False}, content_type='application/json')
        body = b''.join(response.streaming_content).decode()
    assert 'stored complete translation' in body and 'event: complete' in body


def test_missing_provider_returns_actionable_sse_error_without_starting_job(case, client):
    news, _, _, _ = case
    with patch('api.views.get_clients', return_value=[]), patch.object(translation_jobs, 'start_or_get_job') as start:
        response = client.post(f'/api/news/{news.pk}/translate/', {'force': False}, content_type='application/json')
        body = b''.join(response.streaming_content).decode()
    start.assert_not_called()
    assert 'API Key' in body and '未配置全文翻译模型提供方' in body
