"""Integration tests for cross-device / re-entry live attach behavior.

Covers:
1. Serializer exposes full_translation_active=True when a worker is running.
2. POST /translate-full with force=false ATTACHES to in-flight job instead
   of returning the saved snapshot.
3. Serializer flips to full_translation_active=False after worker finishes.
"""

import time
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Category, Source, News
from api.serializers import NewsDetailSerializer
from api.services import translation_jobs


@pytest.fixture(autouse=True)
def clear_jobs():
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()
    yield
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()


@pytest.fixture
def news_obj(db):
    cat = Category.objects.create(name='Tech', slug='tech')
    src = Source.objects.create(name='Hacker News', url='https://news.ycombinator.com', language='en')
    return News.objects.create(
        title='Sample',
        url='https://example.com/a',
        source=src,
        category=cat,
        publish_time=timezone.now(),
        full_content='# Hello\n\nSome English text to translate.',
        full_content_zh='',  # nothing saved yet
    )


def _slow_stream(chunks, delay=0.05):
    def gen(prompt, *a, **kw):
        for c in chunks:
            time.sleep(delay)
            yield c
    return gen


def test_serializer_reports_active_while_worker_runs(news_obj):
    chunks = ['第一段。', '第二段。', '第三段。', '完成。']
    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_slow_stream(chunks, delay=0.1),
    ):
        translation_jobs.start_or_get_job(
            news_id=news_obj.pk,
            prompt='ignored',
            on_save=lambda t, f: None,
        )

        # While running, serializer flag must be True
        time.sleep(0.05)
        data = NewsDetailSerializer(news_obj).data
        assert data['full_translation_active'] is True

        # Drain worker to completion
        deadline = time.time() + 3.0
        while time.time() < deadline:
            job = translation_jobs.get_job(news_obj.pk)
            if job and job.done:
                break
            time.sleep(0.05)

    # After completion, flag must go False
    data = NewsDetailSerializer(news_obj).data
    assert data['full_translation_active'] is False


def test_attach_path_takes_priority_over_snapshot(news_obj, client):
    """When a worker is running AND there's saved partial content, the POST
    endpoint must ATTACH (continue streaming) instead of returning the
    snapshot via the fast-path.
    """
    # Pre-populate some saved partial translation to trigger the old fast-path
    news_obj.full_content_zh = '已有的部分翻译。'
    news_obj.full_content_zh_fetched_at = timezone.now()
    news_obj.save()

    chunks = ['继续 ', '翻译 ', '到 ', '结尾。']

    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_slow_stream(chunks, delay=0.08),
    ):
        # Manually start a job to simulate "worker still running"
        job = translation_jobs.start_or_get_job(
            news_id=news_obj.pk,
            prompt='ignored',
            on_save=lambda t, f: None,
        )
        time.sleep(0.05)  # let worker emit at least one chunk

        # Now hit the endpoint with force=false — should NOT short-circuit
        # to the snapshot path; should attach to the live stream.
        resp = client.post(
            f'/api/news/{news_obj.pk}/translate/',
            data={'force': False},
            content_type='application/json',
        )

        # Consume the streamed body
        body = b''.join(resp.streaming_content).decode('utf-8')

        # Snapshot path would return ONE data: frame and exit immediately.
        # Attach path emits multiple progress frames and eventually 'complete'.
        assert 'event: complete' in body, (
            'Expected attach-path to emit a final complete event; '
            f'got: {body[:500]}'
        )
        # The streamed content should contain chunks from the worker, not
        # ONLY the pre-saved snapshot.
        assert '继续' in body or '翻译' in body


def test_finished_worker_falls_through_to_snapshot(news_obj, client):
    """If the worker has already finished, force=false should serve the
    saved snapshot via the fast path (no new worker spawned).
    """
    news_obj.full_content_zh = '已经翻译完成的全文内容。'
    news_obj.full_content_zh_fetched_at = timezone.now()
    news_obj.save()

    # No active job in the registry
    assert translation_jobs.get_job(news_obj.pk) is None

    # _call_llm_stream must NOT be called (we should hit the snapshot path)
    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=AssertionError('LLM should not be called on snapshot path'),
    ):
        resp = client.post(
            f'/api/news/{news_obj.pk}/translate/',
            data={'force': False},
            content_type='application/json',
        )
        body = b''.join(resp.streaming_content).decode('utf-8')

    assert '已经翻译完成的全文内容。' in body
    # Should be a single snapshot frame, not the attach-path 'complete' event
    assert 'event: complete' not in body
