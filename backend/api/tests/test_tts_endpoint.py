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
    return News.objects.create(
        title='语音测试标题',
        content='语音测试摘要。',
        full_content='语音测试完整正文。',
        url='https://example.com/tts-test',
        source=source,
        category=category,
        publish_time=timezone.now(),
    )


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
