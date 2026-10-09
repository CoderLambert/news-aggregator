import os
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from api.models import SearchIndexRun, SearchIndexSettings
from api.services.embedding import MODEL_NAME


ACTIVE_INDEX_STATUSES = ('queued', 'running', 'cancel_requested')
INDEX_SCHEMA_VERSION = 'news-v1'


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


def get_search_index_settings():
    settings, _ = SearchIndexSettings.objects.get_or_create(
        pk=1,
        defaults={
            'enabled': _env_bool('SEARCH_INDEX_ENABLED', True),
            'interval_seconds': _env_int('SEARCH_INDEX_INTERVAL_SECONDS', 300, 30, 86400),
            'batch_size': _env_int('SEARCH_INDEX_BATCH_SIZE', 100, 1, 500),
            'model_name': MODEL_NAME,
            'schema_version': INDEX_SCHEMA_VERSION,
        },
    )
    return settings


def index_worker_is_online(settings=None):
    settings = settings or get_search_index_settings()
    if not settings.worker_heartbeat_at:
        return False
    return settings.worker_heartbeat_at >= timezone.now() - timedelta(seconds=45)


def index_version_is_current(settings=None):
    settings = settings or get_search_index_settings()
    return (
        settings.model_name == MODEL_NAME
        and settings.schema_version == INDEX_SCHEMA_VERSION
    )


@transaction.atomic
def queue_search_index_run(*, trigger, mode='sync', requested_by=None, crawl_batch=None):
    if mode == 'sync' and not index_version_is_current():
        mode = 'rebuild'
    if crawl_batch is not None:
        existing = SearchIndexRun.objects.filter(crawl_batch=crawl_batch).first()
        if existing is not None:
            return existing, False
    active = (
        SearchIndexRun.objects.select_for_update()
        .filter(status__in=ACTIVE_INDEX_STATUSES)
        .order_by('queued_at')
        .first()
    )
    if active is not None:
        return active, False
    try:
        run = SearchIndexRun.objects.create(
            trigger=trigger,
            mode=mode,
            requested_by=requested_by,
            crawl_batch=crawl_batch,
        )
    except IntegrityError:
        run = SearchIndexRun.objects.filter(status__in=ACTIVE_INDEX_STATUSES).order_by('queued_at').first()
        return run, False
    return run, True


@transaction.atomic
def claim_next_index_run():
    run = (
        SearchIndexRun.objects.select_for_update()
        .filter(status='queued')
        .order_by('queued_at')
        .first()
    )
    if run is None:
        return None
    now = timezone.now()
    run.status = 'running'
    run.started_at = now
    run.heartbeat_at = now
    run.safe_error_code = ''
    run.safe_error_message = ''
    run.save(update_fields=[
        'status', 'started_at', 'heartbeat_at',
        'safe_error_code', 'safe_error_message',
    ])
    return run


def touch_index_worker(instance_id, *, run_id=None):
    now = timezone.now()
    SearchIndexSettings.objects.filter(pk=1).update(
        worker_heartbeat_at=now,
        worker_instance_id=instance_id,
    )
    if run_id:
        SearchIndexRun.objects.filter(
            pk=run_id,
            status__in=['running', 'cancel_requested'],
        ).update(heartbeat_at=now)


def index_run_cancel_requested(run_id):
    return SearchIndexRun.objects.filter(pk=run_id, status='cancel_requested').exists()


@transaction.atomic
def request_index_run_cancel(run_id, user):
    run = SearchIndexRun.objects.select_for_update().get(pk=run_id)
    if run.status == 'queued':
        now = timezone.now()
        run.status = 'cancelled'
        run.cancel_requested_by = user
        run.cancel_requested_at = now
        run.finished_at = now
        run.save(update_fields=[
            'status', 'cancel_requested_by', 'cancel_requested_at', 'finished_at',
        ])
    elif run.status == 'running':
        run.status = 'cancel_requested'
        run.cancel_requested_by = user
        run.cancel_requested_at = timezone.now()
        run.save(update_fields=['status', 'cancel_requested_by', 'cancel_requested_at'])
    return run


def finish_index_run(run_id, *, status, error_code='', error_message=''):
    now = timezone.now()
    values = dict(
        status=status,
        finished_at=now,
        heartbeat_at=now,
        safe_error_code=error_code[:64],
        safe_error_message=error_message[:500],
    )
    if status == 'failed':
        values['failed_count'] = 1
    SearchIndexRun.objects.filter(pk=run_id).update(**values)
    if status == 'succeeded':
        SearchIndexSettings.objects.filter(pk=1).update(last_success_at=now)


def recover_interrupted_index_runs(stale_seconds=300):
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    return SearchIndexRun.objects.filter(
        status__in=['running', 'cancel_requested'],
        heartbeat_at__lt=cutoff,
    ).update(
        status='failed',
        failed_count=1,
        finished_at=timezone.now(),
        safe_error_code='worker_interrupted',
        safe_error_message='索引 Worker 中断，任务可安全重试。',
    )


def schedule_due_index_run():
    settings = get_search_index_settings()
    if not settings.enabled:
        return None
    now = timezone.now()
    if settings.next_run_at and settings.next_run_at > now:
        return None
    run, _ = queue_search_index_run(trigger='scheduled', mode='sync')
    settings.next_run_at = now + timedelta(seconds=settings.interval_seconds)
    settings.save(update_fields=['next_run_at'])
    return run
