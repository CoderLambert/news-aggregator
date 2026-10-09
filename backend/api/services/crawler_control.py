import os
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from api.management.commands.crawl import SPIDERS
from api.models import CrawlBatch, CrawlRun, CrawlerSettings, CrawlerTarget


ACTIVE_RUN_STATUSES = ('queued', 'running', 'cancel_requested')


class NoTargetsQueued(Exception):
    pass


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_interval():
    try:
        return max(60, int(os.environ.get('CRAWL_INTERVAL_SECONDS', '3600')))
    except (TypeError, ValueError):
        return 3600


def get_crawler_settings():
    settings, _ = CrawlerSettings.objects.get_or_create(
        pk=1,
        defaults={
            'scheduler_enabled': _env_bool('CRAWLER_SCHEDULER_ENABLED', True),
            'interval_seconds': _env_interval(),
            'run_on_worker_start': _env_bool('CRAWL_RUN_ON_START', True),
        },
    )
    return settings


def display_name(spider_name):
    return spider_name.replace('_', ' ').title()


def sync_crawler_targets():
    existing = set(CrawlerTarget.objects.values_list('spider_name', flat=True))
    for sort_order, spider_name in enumerate(SPIDERS):
        CrawlerTarget.objects.update_or_create(
            spider_name=spider_name,
            defaults={
                'display_name': display_name(spider_name),
                'sort_order': sort_order,
            },
        )
        existing.discard(spider_name)
    if existing:
        CrawlerTarget.objects.filter(spider_name__in=existing).update(enabled=False)


@transaction.atomic
def create_crawl_batch(*, trigger, requested_by=None, spider_names=None, retry_of=None):
    sync_crawler_targets()
    targets = CrawlerTarget.objects.select_for_update().filter(enabled=True)
    if spider_names is not None:
        targets = targets.filter(spider_name__in=spider_names)
    targets = list(targets.order_by('sort_order', 'spider_name'))
    if not targets:
        raise NoTargetsQueued('没有已启用的爬虫来源。')

    active = {
        run.target_id: run
        for run in CrawlRun.objects.select_related('target').filter(
            target__in=targets,
            status__in=ACTIVE_RUN_STATUSES,
        )
    }
    queue_targets = [target for target in targets if target.spider_name not in active]
    if not queue_targets:
        return None, list(active.values())

    batch = CrawlBatch.objects.create(
        trigger=trigger,
        requested_by=requested_by,
        total=len(queue_targets),
    )
    try:
        with transaction.atomic():
            CrawlRun.objects.bulk_create([
                CrawlRun(
                    batch=batch,
                    target=target,
                    requested_by=requested_by,
                    retry_of=retry_of if len(queue_targets) == 1 else None,
                )
                for target in queue_targets
            ])
    except IntegrityError:
        batch.delete()
        current = list(CrawlRun.objects.filter(
            target__in=targets,
            status__in=ACTIVE_RUN_STATUSES,
        ))
        return None, current
    return batch, list(active.values())


@transaction.atomic
def claim_next_run():
    run = (
        CrawlRun.objects.select_for_update()
        .select_related('batch', 'target')
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
    run.save(update_fields=['status', 'started_at', 'heartbeat_at'])
    if run.batch.status == 'queued':
        run.batch.status = 'running'
        run.batch.started_at = run.batch.started_at or now
        run.batch.save(update_fields=['status', 'started_at'])
    CrawlerTarget.objects.filter(pk=run.target_id).update(
        last_status='running',
        last_started_at=now,
        last_safe_error='',
    )
    return run


def touch_worker(instance_id, *, run_id=None):
    now = timezone.now()
    CrawlerSettings.objects.filter(pk=1).update(
        worker_heartbeat_at=now,
        worker_instance_id=instance_id,
    )
    if run_id:
        CrawlRun.objects.filter(pk=run_id, status__in=['running', 'cancel_requested']).update(
            heartbeat_at=now,
        )


def recompute_batch(batch_id):
    counts = {
        row['status']: row['count']
        for row in CrawlRun.objects.filter(batch_id=batch_id)
        .values('status')
        .annotate(count=Count('id'))
    }
    active = sum(counts.get(value, 0) for value in ACTIVE_RUN_STATUSES)
    succeeded = counts.get('succeeded', 0)
    failed = counts.get('failed', 0) + counts.get('skipped', 0)
    cancelled = counts.get('cancelled', 0)
    updates = {
        'succeeded': succeeded,
        'failed': failed,
        'cancelled': cancelled,
    }
    if active:
        updates['status'] = 'running' if counts.get('running', 0) or counts.get('cancel_requested', 0) else 'queued'
    else:
        updates['finished_at'] = timezone.now()
        if failed and succeeded:
            updates['status'] = 'partial'
        elif failed:
            updates['status'] = 'failed'
        elif cancelled and succeeded:
            updates['status'] = 'partial'
        elif cancelled:
            updates['status'] = 'cancelled'
        else:
            updates['status'] = 'succeeded'
    CrawlBatch.objects.filter(pk=batch_id).update(**updates)
    if not active and updates.get('status') in {'succeeded', 'partial', 'failed', 'cancelled'}:
        # Queue only a durable local-index reconciliation. The crawler remains
        # crawl-only and never performs translation or external AI calls.
        from api.services.search_index_control import (
            get_search_index_settings,
            queue_search_index_run,
        )
        batch = CrawlBatch.objects.filter(pk=batch_id).first()
        if batch is not None and get_search_index_settings().enabled:
            queue_search_index_run(
                trigger='crawl_batch',
                mode='sync',
                crawl_batch=batch,
            )


@transaction.atomic
def finish_run(run_id, *, status, exit_code, summary=None, safe_error='', log_path=''):
    summary = summary or {}
    now = timezone.now()
    run = CrawlRun.objects.select_related('target').get(pk=run_id)
    run.status = status
    run.exit_code = exit_code
    run.finished_at = now
    run.heartbeat_at = now
    run.items = max(0, int(summary.get('items', 0)))
    run.responses = max(0, int(summary.get('responses', 0)))
    run.errors = max(0, int(summary.get('errors', 0)))
    run.http_statuses = summary.get('http_statuses', {})
    run.stats = {'finish_reason': summary.get('finish_reason', '')}
    run.safe_error = safe_error[:500]
    run.log_path = log_path[:500]
    run.save(update_fields=[
        'status', 'exit_code', 'finished_at', 'heartbeat_at', 'items',
        'responses', 'errors', 'http_statuses', 'stats', 'safe_error', 'log_path',
    ])
    CrawlerTarget.objects.filter(pk=run.target_id).update(
        last_status=status,
        last_finished_at=now,
        last_items=run.items,
        last_responses=run.responses,
        last_errors=run.errors,
        last_safe_error=run.safe_error,
    )
    recompute_batch(run.batch_id)


@transaction.atomic
def request_run_cancel(run_id, user):
    run = CrawlRun.objects.select_for_update().select_related('target').get(pk=run_id)
    if run.status == 'queued':
        now = timezone.now()
        run.status = 'cancelled'
        run.cancel_requested_by = user
        run.cancel_requested_at = now
        run.finished_at = now
        run.safe_error = '任务在开始前由管理员取消。'
        run.save(update_fields=[
            'status', 'cancel_requested_by', 'cancel_requested_at',
            'finished_at', 'safe_error',
        ])
        CrawlerTarget.objects.filter(pk=run.target_id).update(
            last_status='cancelled',
            last_finished_at=now,
            last_safe_error=run.safe_error,
        )
        recompute_batch(run.batch_id)
    elif run.status == 'running':
        run.status = 'cancel_requested'
        run.cancel_requested_by = user
        run.cancel_requested_at = timezone.now()
        run.save(update_fields=['status', 'cancel_requested_by', 'cancel_requested_at'])
    return run


def recover_interrupted_runs():
    interrupted = list(CrawlRun.objects.filter(status__in=['running', 'cancel_requested']).values_list('pk', flat=True))
    for run_id in interrupted:
        finish_run(
            run_id,
            status='failed',
            exit_code=None,
            safe_error='Crawler Worker 重启，中断的任务未自动重放。',
        )
    return len(interrupted)


@transaction.atomic
def schedule_due_batch():
    settings = CrawlerSettings.objects.select_for_update().get(pk=1)
    if not settings.scheduler_enabled:
        return None
    now = timezone.now()
    if settings.next_run_at is None:
        if not settings.run_on_worker_start:
            settings.next_run_at = now + timedelta(seconds=settings.interval_seconds)
            settings.save(update_fields=['next_run_at'])
            return None
        trigger = 'startup'
    elif settings.next_run_at > now:
        return None
    else:
        trigger = 'scheduled'
    # A full crawl can take longer than its configured interval. Keep one
    # global queue instead of adding another partial scheduled batch while
    # the previous queue is still being processed.
    if CrawlRun.objects.filter(status__in=ACTIVE_RUN_STATUSES).exists():
        return None
    settings.next_run_at = now + timedelta(seconds=settings.interval_seconds)
    settings.save(update_fields=['next_run_at'])
    try:
        batch, _ = create_crawl_batch(trigger=trigger)
    except NoTargetsQueued:
        return None
    return batch


def worker_is_online(settings, *, threshold_seconds=45):
    if not settings.worker_heartbeat_at:
        return False
    return settings.worker_heartbeat_at >= timezone.now() - timedelta(seconds=threshold_seconds)
