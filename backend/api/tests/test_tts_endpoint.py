from api.tests.rss.reader_fixtures import public_legacy_article
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from api.models import Category, News, Source
from api.services.tts_service import configure_edge_tts_endpoint


@pytest.fixture
def tts_news(db):
    source = Source.objects.create(
        name='TTS Test Source',
        url='https://example.com',
        language='zh',
        source_type='news',
    )
    category = Category.objects.create(name='TTS', slug='tts')
    return public_legacy_article(News.objects.create(
        title='语音测试标题',
        content='语音测试摘要。',
        full_content='语音测试完整正文。',
        url='https://example.com/tts-test',
        source=source,
        category=category,
        publish_time=timezone.now(),
    ))


@override_settings(EDGE_TTS_ENDPOINT='msedgeservices')
def test_configure_edge_tts_uses_reviewed_msedgeservices_endpoint(monkeypatch):
    from edge_tts import communicate

    monkeypatch.setattr(communicate, 'WSS_URL', 'wss://default.invalid/edge/v1')
    selected = configure_edge_tts_endpoint()

    assert selected.startswith(
        'wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?'
    )
    assert communicate.WSS_URL == selected


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_returns_503_when_upstream_handshake_fails(client, tts_news):
    user = get_user_model().objects.create_user(username='tts-upstream-failure')
    client.force_login(user)

    class FailingCommunicate:
        def __init__(self, *_args, **_kwargs):
            pass

        async def stream(self):
            if False:
                yield None
            raise RuntimeError('simulated handshake failure')

    with patch('edge_tts.Communicate', FailingCommunicate), patch(
        'api.services.tts_service.configure_edge_tts_endpoint',
        return_value='wss://reviewed.invalid',
    ):
        response = client.get(
            reverse('news-tts', args=[tts_news.pk]),
            {'language': 'original', 'scope': 'summary'},
        )

    assert response.status_code == 503
    assert response.json() == {
        'code': 'tts_unavailable',
        'message': '语音服务暂不可用，请稍后重试。',
    }


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_streams_and_caches_audio_after_success(client, tts_news, tmp_path):
    user = get_user_model().objects.create_user(username='tts-upstream-success')
    client.force_login(user)

    class WorkingCommunicate:
        def __init__(self, *_args, **_kwargs):
            pass

        async def stream(self):
            yield {'type': 'audio', 'data': b'first-audio-chunk'}
            yield {'type': 'audio', 'data': b'second-audio-chunk'}

    with override_settings(TTS_CACHE_DIR=tmp_path), patch(
        'edge_tts.Communicate', WorkingCommunicate,
    ), patch(
        'api.services.tts_service.configure_edge_tts_endpoint',
        return_value='wss://reviewed.invalid',
    ):
        response = client.get(
            reverse('news-tts', args=[tts_news.pk]),
            {'language': 'original', 'scope': 'summary'},
        )
        body = b''.join(response.streaming_content)

    assert response.status_code == 200
    assert response['Content-Type'] == 'audio/mpeg'
    assert body == b'first-audio-chunksecond-audio-chunk'
    cached_files = list(tmp_path.glob('*.mp3'))
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == body

@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_atomic_cache_remains_invisible_until_stream_finishes(client, tts_news, tmp_path):
    from api.services.tts_service import get_cached_audio, build_cache_variant, resolve_tts_content, clean_for_tts, pick_tts_voice
    user = get_user_model().objects.create_user(username='tts-atomic')
    client.force_login(user)

    class Working:
        def __init__(self, *_a, **_kw):
            pass
        async def stream(self):
            yield {'type': 'audio', 'data': b'X' * 140}
            yield {'type': 'audio', 'data': b'Y' * 180}

    with override_settings(TTS_CACHE_DIR=tmp_path), patch('edge_tts.Communicate', Working), patch(
        'api.services.tts_service.configure_edge_tts_endpoint', return_value='wss://reviewed.invalid'
    ):
        response = client.get(reverse('news-tts', args=[tts_news.pk]), {'language': 'original', 'scope': 'summary'})
        read = iter(response.streaming_content)
        assert next(read) == b'X' * 140
        assert list(tmp_path.glob('*.mp3')) == []
        assert len(list(tmp_path.glob('*.part'))) == 1
        assert b''.join(read) == b'Y' * 180
        files = list(tmp_path.glob('*.mp3'))
        assert len(files) == 1 and files[0].read_bytes() == b'X' * 140 + b'Y' * 180
        assert list(tmp_path.glob('*.part')) == []


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_interrupted_stream_leaves_no_partial_audio(client, tts_news, tmp_path):
    user = get_user_model().objects.create_user(username='tts-interrupt')
    client.force_login(user)

    class Broken:
        def __init__(self, *_a, **_kw):
            pass
        async def stream(self):
            yield {'type': 'audio', 'data': b'X' * 140}
            raise RuntimeError('synthetic disconnect')

    with override_settings(TTS_CACHE_DIR=tmp_path), patch('edge_tts.Communicate', Broken), patch(
        'api.services.tts_service.configure_edge_tts_endpoint', return_value='wss://reviewed.invalid'
    ):
        response = client.get(reverse('news-tts', args=[tts_news.pk]), {'language': 'original', 'scope': 'summary'})
        chunks = iter(response.streaming_content)
        assert next(chunks) == b'X' * 140
        with pytest.raises(RuntimeError, match='tts_stream_interrupted'):
            list(chunks)
        assert not list(tmp_path.iterdir())


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_oversized_speech_rejected_before_connecting(client, tts_news):
    user = get_user_model().objects.create_user(username='tts-too-long')
    client.force_login(user)
    tts_news.content = 'large words ' * 2400
    tts_news.save(update_fields=['content'])
    with patch('edge_tts.Communicate') as provider:
        response = client.get(reverse('news-tts', args=[tts_news.pk]), {'language': 'original', 'scope': 'summary'})
    assert response.status_code == 413
    assert response.json()['code'] == 'tts_text_too_long'
    provider.assert_not_called()


def test_atomic_audio_replacement_cleans_stage_when_replace_fails(monkeypatch, tmp_path):
    from api.services import tts_service as tts
    with override_settings(TTS_CACHE_DIR=tmp_path):
        prior = tts.save_to_cache(1, 'voice-variant', b'A' * 140)
        original = open(prior, 'rb').read()
        def fail(*_a, **_k):
            raise OSError('synthetic replace error')
        monkeypatch.setattr(tts.os, 'replace', fail)
        with pytest.raises(OSError):
            tts.save_to_cache(1, 'voice-variant', b'B' * 150)
        assert open(prior, 'rb').read() == original
        assert not list(tmp_path.glob('*.part'))


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_check_validates_without_synthesis_or_cache(client, tts_news, tmp_path):
    user = get_user_model().objects.create_user(username='tts-check')
    tts_news.full_content_state = 'available'
    tts_news.save(update_fields=['full_content_state'])
    client.force_login(user)
    with override_settings(TTS_CACHE_DIR=tmp_path), patch('edge_tts.Communicate') as provider:
        response = client.get(reverse('news-tts', args=[tts_news.pk]), {
            'language': 'original', 'scope': 'full', 'check': '1', 'voice': 'guy',
        })
    assert response.status_code == 200
    assert response['Content-Type'].startswith('application/json')
    assert response['Cache-Control'] == 'private, no-store'
    assert response.json()['language'] == 'zh'
    assert response.json()['voice'].startswith('zh-CN-')
    assert response.json()['status'] == 'ready'
    provider.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_check_unknown_language_requires_chinese_translation_but_allows_original(client, tts_news):
    user = get_user_model().objects.create_user(username='tts-check-unknown')
    tts_news.full_content_state = 'available'
    tts_news.save(update_fields=['full_content_state'])
    client.force_login(user)
    tts_news.source.language = ''
    tts_news.source.save(update_fields=['language'])
    with patch('edge_tts.Communicate') as provider:
        denied = client.get(reverse('news-tts', args=[tts_news.pk]), {
            'language': 'zh', 'scope': 'full', 'check': '1',
        })
        ready = client.get(reverse('news-tts', args=[tts_news.pk]), {
            'language': 'original', 'scope': 'full', 'check': '1',
        })
    assert denied.status_code == 409
    assert denied.json()['code'] == 'translation_required'
    assert ready.status_code == 200
    assert ready.json()['language'] == 'original'
    provider.assert_not_called()


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_tts_check_enforces_auth_and_explicit_translation_identity(client, tts_news):
    url = reverse('news-tts', args=[tts_news.pk])
    with patch('edge_tts.Communicate') as provider:
        assert client.get(url, {'check': '1'}).status_code == 403
        user = get_user_model().objects.create_user(username='tts-check-private')
        client.force_login(user)
        tts_news.full_content_state = 'available'
        tts_news.source.language = ''
        tts_news.save(update_fields=['full_content_state'])
        tts_news.source.save(update_fields=['language'])
        response = client.get(url, {'check': '1', 'language': 'zh', 'scope': 'full',
                                    'translation_result_id': '999999'})
    assert response.status_code == 404
    assert response.json()['code'] == 'translation_result_unavailable'
    provider.assert_not_called()
