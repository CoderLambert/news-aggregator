"""DB-only first-submission races; all provider work is forbidden."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from unittest.mock import Mock

import pytest
from django.db import OperationalError, close_old_connections, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.db.models.query import QuerySet

from api.models import ChatGPTSubscriptionConnection, ChatGPTTranslationTask, News
from api.services import chatgpt_subscription as subscription, chatgpt_subscription_jobs as jobs
from api.services import shared_translations
from api.tests.test_subscription_recovery import owner, article, local_mode, make_connection

pytestmark = pytest.mark.django_db(transaction=True)


def locked(code=sqlite3.SQLITE_LOCKED):
    driver = sqlite3.OperationalError('synthetic coded SQLite error')
    driver.sqlite_errorcode = code
    wrapped = OperationalError('wrapped driver error')
    wrapped.__cause__ = driver
    return wrapped


def first_insert_race(monkeypatch):
    reads = threading.Barrier(2)
    inserts = threading.Barrier(2)
    seen_reads, seen_inserts, errors = set(), set(), []
    lock = threading.Lock()
    get, execute = QuerySet.get, CursorWrapper.execute

    def raced_get(query, *args, **kwargs):
        try:
            return get(query, *args, **kwargs)
        except query.model.DoesNotExist:
            if query.model is ChatGPTTranslationTask:
                name = threading.current_thread().name
                with lock:
                    first = name not in seen_reads
                    seen_reads.add(name)
                if first:
                    reads.wait(timeout=5)
            raise

    def raced_execute(cursor, sql, params=None):
        is_insert = sql.upper().startswith('INSERT INTO "API_CHATGPTTRANSLATIONTASK"')
        name = threading.current_thread().name
        with lock:
            first = is_insert and name not in seen_inserts
            if first:
                seen_inserts.add(name)
        try:
            return execute(cursor, sql, params)
        except OperationalError as error:
            if first:
                errors.append(error)
            raise
        finally:
            if first:
                # Keep the original transaction open until both inserts have
                # attempted. Memory SQLite fails both; WAL allows one writer.
                inserts.wait(timeout=5)

    monkeypatch.setattr(QuerySet, 'get', raced_get)
    monkeypatch.setattr(CursorWrapper, 'execute', raced_execute)
    return errors


def simultaneous_submission(owner, article, monkeypatch):
    account = make_connection(owner)
    monkeypatch.setattr(jobs, '_dispatching', set())
    dispatches = []
    def submit_provider(*args):
        assert not connection.in_atomic_block
        dispatches.append(args)
    monkeypatch.setattr(jobs._executor, 'submit', submit_provider)
    monkeypatch.setattr(jobs, 'stream_full_translation', Mock(side_effect=AssertionError('provider forbidden')))
    errors = first_insert_race(monkeypatch)

    def submit():
        close_old_connections()
        try:
            user = type(owner).objects.get(pk=owner.pk)
            account_copy = ChatGPTSubscriptionConnection.objects.get(pk=account.pk)
            news = News.objects.get(pk=article.pk)
            return jobs.start_or_get_job(user, account_copy, news).id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        handles = list(executor.map(lambda _: submit(), range(2)))
    assert handles[0] == handles[1]
    assert ChatGPTTranslationTask.objects.count() == 1
    assert ChatGPTTranslationTask.objects.get().generation == 1
    assert len(dispatches) == 1
    assert errors and all(jobs._is_submission_sqlite_lock(error) for error in errors)
    jobs.stream_full_translation.assert_not_called()
    return len(errors)


def test_first_creation_race_commits_one_task_and_dispatches_once(owner, article, monkeypatch):
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode')
        mode = cursor.fetchone()[0]
    assert mode in {'memory', 'wal'}, mode
    assert simultaneous_submission(owner, article, monkeypatch) == (2 if mode == 'memory' else 1)


def test_failed_transaction_rolls_back_and_keeps_owned_lease(owner, article, monkeypatch):
    account = make_connection(owner)
    lease = shared_translations.claim_task(article)
    original = ChatGPTTranslationTask.objects.get_or_create
    attempts = []
    def create_then_lock(**kwargs):
        result = original(**kwargs)
        attempts.append(1)
        if len(attempts) == 1:
            raise locked()
        assert lease.current().exists()
        return result
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create_then_lock)
    dispatch = Mock(side_effect=lambda *_args: None)
    monkeypatch.setattr(jobs, '_dispatch_task', dispatch)
    handle = jobs.start_or_get_job(owner, account, article, shared_lease=lease)
    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert len(attempts) == 2
    assert ChatGPTTranslationTask.objects.count() == 1
    assert task.shared_lease_token == lease.token and lease.current().exists()
    assert task.generation == 1
    dispatch.assert_called_once()


@pytest.mark.parametrize('error', [OperationalError('database is locked'), locked(sqlite3.SQLITE_FULL), locked(sqlite3.SQLITE_IOERR)])
def test_non_lock_errors_do_not_retry_or_dispatch(owner, article, monkeypatch, error):
    account = make_connection(owner)
    create = Mock(side_effect=error)
    dispatch = Mock()
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create)
    monkeypatch.setattr(jobs, '_dispatch_task', dispatch)
    with pytest.raises(subscription.SubscriptionError) as caught:
        jobs.start_or_get_job(owner, account, article)
    assert caught.value.error_code == 'task_storage_busy'
    assert create.call_count == 1
    dispatch.assert_not_called()


def test_bounded_exhaustion_releases_only_owned_lease(owner, article, monkeypatch):
    account = make_connection(owner)
    lease = shared_translations.claim_task(article)
    create = Mock(side_effect=locked())
    dispatch = Mock()
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create)
    monkeypatch.setattr(jobs, '_dispatch_task', dispatch)
    sleeps = []
    monkeypatch.setattr(jobs.time, 'sleep', lambda delay: sleeps.append(delay))
    with pytest.raises(subscription.SubscriptionError):
        jobs.start_or_get_job(owner, account, article, shared_lease=lease)
    assert create.call_count == len(jobs.SUBMISSION_LOCK_DELAYS) + 1
    assert len(sleeps) == len(jobs.SUBMISSION_LOCK_DELAYS)
    assert not lease.current().exists()
    assert ChatGPTTranslationTask.objects.count() == 0
    dispatch.assert_not_called()


def test_revalidation_after_retry_rejects_changed_connection(owner, article, monkeypatch):
    account = make_connection(owner)
    create = Mock(side_effect=locked())
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create)
    def change_account(_delay):
        ChatGPTSubscriptionConnection.objects.filter(pk=account.pk).update(generation=2)
    monkeypatch.setattr(jobs.time, 'sleep', change_account)
    with pytest.raises(subscription.ConnectionChangedError):
        jobs.start_or_get_job(owner, account, article)
    assert create.call_count == 1
    assert ChatGPTTranslationTask.objects.count() == 0


def test_nested_transaction_does_not_retry(owner, article, monkeypatch):
    account = make_connection(owner)
    create = Mock(side_effect=locked())
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create)
    with transaction.atomic(), pytest.raises(subscription.SubscriptionError):
        jobs.start_or_get_job(owner, account, article)
    assert create.call_count == 1


def test_force_does_not_retry_task_creation(owner, article, monkeypatch):
    account = make_connection(owner)
    create = Mock(side_effect=locked())
    monkeypatch.setattr(ChatGPTTranslationTask.objects, 'get_or_create', create)
    monkeypatch.setattr(jobs.time, 'sleep', lambda _delay: None)
    with pytest.raises(subscription.SubscriptionError):
        jobs.start_or_get_job(owner, account, article, force=True)
    assert create.call_count == 1


def test_non_sqlite_vendor_does_not_retry(owner, article, monkeypatch):
    monkeypatch.setattr(connection, 'vendor', 'other')
    operation = Mock(side_effect=locked())
    with pytest.raises(OperationalError):
        jobs._retry_submission_transaction(operation)
    operation.assert_called_once()


def test_force_reset_rolls_back_without_replaying_generation(owner, article, monkeypatch):
    account = make_connection(owner)
    monkeypatch.setattr(jobs, '_dispatch_task', Mock())
    handle = jobs.start_or_get_job(owner, account, article)
    ChatGPTTranslationTask.objects.filter(pk=handle.id).update(status='failed')
    original = jobs._reset_task
    calls = []
    def reset_then_lock(*args, **kwargs):
        calls.append(1)
        original(*args, **kwargs)
        raise locked()
    monkeypatch.setattr(jobs, '_reset_task', reset_then_lock)
    with pytest.raises(subscription.SubscriptionError):
        jobs.start_or_get_job(owner, account, article, force=True)
    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert len(calls) == 1
    assert task.generation == 1 and task.status == 'failed'
    # Only the original creation was dispatched, never the failed force reset.
    assert jobs._dispatch_task.call_count == 1
