"""Tests for the background translation job manager.

Verifies that:
1. A job survives client "disconnect" — i.e., the worker keeps running even
   when no one is reading job.text.
2. A second caller attaches to an in-flight job rather than starting a new one.
3. on_save is called periodically and once finally.
4. Errors from the LLM stream propagate to job.error and finish the job.
"""

import time
import threading
from unittest.mock import patch

import pytest

from api.services import translation_jobs


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear in-memory job registry between tests."""
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()
    yield
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()


def _fake_stream(chunks, delay=0.01):
    """Build a fake _call_llm_stream generator that yields each chunk with delay."""
    def gen(prompt, *args, **kwargs):
        for c in chunks:
            time.sleep(delay)
            yield c
    return gen


def test_job_completes_without_any_reader():
    """The worker thread must finish even if NO one reads job.text — this is
    exactly the 'client refreshed and went away' scenario.
    """
    saves = []
    chunks = ['hello ', 'world ', '中文 ', '段落。']

    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_fake_stream(chunks),
    ):
        job = translation_jobs.start_or_get_job(
            news_id=101,
            prompt='ignored',
            on_save=lambda text, final: saves.append((text, final)),
            save_every_chars=1,  # save on every chunk for deterministic assertions
        )

        # Wait up to 2s for the worker to finish — no one is reading the stream
        deadline = time.time() + 2.0
        while not job.done and time.time() < deadline:
            time.sleep(0.02)

    assert job.done is True
    assert job.error is None
    assert job.text == 'hello world 中文 段落。'
    # Final save must have been called with is_final=True
    assert saves[-1] == ('hello world 中文 段落。', True)
    # There should be at least one progress save (chars>=1 → every chunk)
    assert len(saves) >= 2


def test_second_caller_attaches_to_existing_job():
    """When a job is already running for news_id, start_or_get_job must
    return the SAME instance instead of spawning a parallel worker.
    """
    chunks = ['a', 'b', 'c', 'd', 'e']

    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_fake_stream(chunks, delay=0.05),
    ):
        job1 = translation_jobs.start_or_get_job(202, 'p', lambda t, f: None)
        # Give the worker a moment to actually be in-flight
        time.sleep(0.02)
        job2 = translation_jobs.start_or_get_job(202, 'p', lambda t, f: None)

        assert job1 is job2

        # Wait for completion
        deadline = time.time() + 2.0
        while not job1.done and time.time() < deadline:
            time.sleep(0.02)

    assert job1.done is True
    assert job1.text == 'abcde'


def test_wait_for_update_unblocks_on_new_chunk():
    """A reader blocked in wait_for_update must be notified when new text
    arrives — this is what the SSE generator depends on for responsiveness.
    """
    chunks = ['x'] + ['y'] * 5

    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_fake_stream(chunks, delay=0.03),
    ):
        job = translation_jobs.start_or_get_job(303, 'p', lambda t, f: None)

        start = time.time()
        new_len = job.wait_for_update(0, timeout=1.0)
        elapsed = time.time() - start

        # Must have unblocked well before the 1.0s timeout
        assert new_len > 0
        assert elapsed < 0.8

        # Drain remainder
        deadline = time.time() + 2.0
        while not job.done and time.time() < deadline:
            time.sleep(0.02)
        assert job.done is True


def test_error_chunk_finishes_job_with_error():
    """If the LLM stream's first emission is an 'Error: ...' string (no
    real content yet), the job must finish in error state.
    """
    def err_stream(prompt, *a, **kw):
        yield 'Error: 上游 LLM 超时'

    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=err_stream,
    ):
        job = translation_jobs.start_or_get_job(404, 'p', lambda t, f: None)
        deadline = time.time() + 1.0
        while not job.done and time.time() < deadline:
            time.sleep(0.02)

    assert job.done is True
    assert job.error and '超时' in job.error
    assert job.text == ''


def test_finished_job_returned_then_new_one_starts_on_next_call():
    """Once a job is done, the registry should NOT keep handing it back as
    'in-flight'. The next call starts a fresh worker.
    """
    with patch(
        'api.services.llm_translator._call_llm_stream',
        side_effect=_fake_stream(['done']),
    ):
        job1 = translation_jobs.start_or_get_job(505, 'p', lambda t, f: None)
        deadline = time.time() + 1.0
        while not job1.done and time.time() < deadline:
            time.sleep(0.02)
        assert job1.done is True

        # A new call after completion should produce a new job instance
        job2 = translation_jobs.start_or_get_job(505, 'p', lambda t, f: None)
        deadline = time.time() + 1.0
        while not job2.done and time.time() < deadline:
            time.sleep(0.02)

    assert job2 is not job1
    assert job2.done is True
