"""Real competing reader + DB-only rollback tests; fake provider only."""
import inspect
import threading
import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.db import OperationalError, close_old_connections, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.db.models.query import QuerySet
from django.utils import timezone

from api.models import ChatGPTTranslationTask, ChatGPTArticleTranslation, SharedArticleTranslation
from api.services import chatgpt_subscription_jobs as jobs, chatgpt_subscription as subscription, shared_translations
from api.tests.test_subscription_recovery import owner, article, local_mode, make_connection
from api.tests.test_subscription_recovery import test_sse_disconnect_does_not_cancel_background_worker as sse_contract
from api.tests.test_subscription_submission_locks import locked

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize('stage', ['_mark_provider_started', '_append_delta', '_finalize_task'])
def test_sse_success_with_temporary_task_reader(owner, article, monkeypatch, stage):
    ready, held, release, done = [threading.Event() for _ in range(4)]
    injected = []
    errors = []
    reader_errors = []
    original = CursorWrapper.execute
    def competing_reader():
        close_old_connections()
        try:
            assert ready.wait(5)
            with transaction.atomic():
                assert ChatGPTTranslationTask.objects.values('id').first()
                held.set()
                assert release.wait(5)
        except Exception as error:
            reader_errors.append(error)
        finally:
            close_old_connections()
            done.set()
    def execute(cursor, sql, params=None):
        inject = False
        if sql.upper().startswith('UPDATE "API_CHATGPTTRANSLATIONTASK"') and not injected:
            stack = [frame.function for frame in inspect.stack() if frame.filename.endswith('chatgpt_subscription_jobs.py')]
            if stage in stack:
                injected.append(stage)
                inject = True
                ready.set()
                assert held.wait(5)
        try:
            return original(cursor, sql, params)
        except OperationalError as error:
            if inject:
                errors.append(error)
            raise
        finally:
            if inject:
                release.set()
                assert done.wait(5)
    monkeypatch.setattr(CursorWrapper, 'execute', execute)
    reader = threading.Thread(target=competing_reader, name='temporary-task-reader')
    reader.start()
    try:
        sse_contract(owner, article, monkeypatch)
    finally:
        release.set()
        reader.join(6)
    assert not reader.is_alive() and not reader_errors
    assert injected == [stage]
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode')
        mode = cursor.fetchone()[0]
    assert mode in {'memory', 'wal'}
    assert len(errors) == (1 if mode == 'memory' else 0)
    assert all(jobs._is_task_sqlite_lock(error) for error in errors)
    assert ChatGPTTranslationTask.objects.get().progress == 'visible progress'


def running(owner, article, monkeypatch, *, started=True, with_lease=False):
    account = make_connection(owner)
    lease = shared_translations.claim_task(article) if with_lease else None
    monkeypatch.setattr(jobs, '_dispatch_task', Mock())
    handle = jobs.start_or_get_job(owner, account, article, shared_lease=lease)
    token = uuid.uuid4()
    ChatGPTTranslationTask.objects.filter(pk=handle.id).update(status='running', run_token=token,
        provider_started=started, lease_expires_at=timezone.now()+timedelta(seconds=60))
    return handle, token, lease


def test_progress_rollback_retries_without_duplicate_delta(owner, article, monkeypatch):
    handle, token, _ = running(owner, article, monkeypatch)
    original = QuerySet.update
    attempts = []
    def update(query, **kwargs):
        result = original(query, **kwargs)
        if query.model is ChatGPTTranslationTask and 'progress' in kwargs:
            attempts.append(1)
            if len(attempts) == 1:
                raise locked()
        return result
    monkeypatch.setattr(QuerySet, 'update', update)
    jobs._append_delta(handle.id, 1, token, 'one delta')
    assert len(attempts) == 2
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).progress == 'one delta'


def test_result_rollback_retries_one_private_and_shared_result(owner, article, monkeypatch):
    handle, token, lease = running(owner, article, monkeypatch, with_lease=True)
    original = QuerySet.update
    attempts = []
    def update(query, **kwargs):
        result = original(query, **kwargs)
        if query.model is ChatGPTTranslationTask and kwargs.get('status') == 'succeeded':
            attempts.append(1)
            if len(attempts) == 1:
                raise locked()
        return result
    monkeypatch.setattr(QuerySet, 'update', update)
    jobs._finalize_task(handle.id, 1, token, 'fake complete result')
    assert len(attempts) == 2
    assert ChatGPTArticleTranslation.objects.count() == SharedArticleTranslation.objects.count() == 1
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).status == 'succeeded'
    assert not lease.current().exists()


def test_progress_retry_revalidates_cancellation(owner, article, monkeypatch):
    handle, token, _ = running(owner, article, monkeypatch)
    original = QuerySet.update
    calls = []
    def update(query, **kwargs):
        if query.model is ChatGPTTranslationTask and 'progress' in kwargs:
            calls.append(1)
            raise locked()
        return original(query, **kwargs)
    def cancel(_delay):
        original(ChatGPTTranslationTask.objects.filter(pk=handle.id), status='cancelled', run_token=None)
    monkeypatch.setattr(QuerySet, 'update', update)
    monkeypatch.setattr(jobs.time, 'sleep', cancel)
    with pytest.raises(subscription.SubscriptionError):
        jobs._append_delta(handle.id, 1, token, 'never committed')
    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert len(calls) == 1 and task.status == 'cancelled' and task.progress == ''


@pytest.mark.parametrize('code', [None, 13])
def test_worker_non_lock_error_never_retries(owner, article, monkeypatch, code):
    handle, token, _ = running(owner, article, monkeypatch, started=False)
    error = OperationalError('unknown') if code is None else locked(code)
    original = QuerySet.update
    calls = []
    def update(query, **kwargs):
        if query.model is ChatGPTTranslationTask and kwargs.get('provider_started') is True:
            calls.append(1)
            raise error
        return original(query, **kwargs)
    monkeypatch.setattr(QuerySet, 'update', update)
    with pytest.raises(OperationalError):
        jobs._mark_provider_started(handle.id, 1, token)
    assert len(calls) == 1
    assert not ChatGPTTranslationTask.objects.get(pk=handle.id).provider_started
