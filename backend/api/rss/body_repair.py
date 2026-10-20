"""Local operator orchestration; collection and writes stay with existing workers."""
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation
from api.rss.operations import OperationError, enqueue_operation, refetch_fence


def preview(*, days=7, target_url=None):
    cutoff = timezone.now() - timedelta(days=days)
    entries = EngineEntryMap.objects.filter(news__isnull=False).select_related('news', 'binding')
    if target_url:
        entries = entries.filter(source_url=target_url)
    else:
        entries = entries.filter(news__publish_time__gte=cutoff, news__publish_time__lte=timezone.now())
    rows = []
    for entry in entries.order_by('binding_id', 'engine_entry_id'):
        row = dict(entry=str(entry.pk), binding=str(entry.binding_id), news=entry.news_id,
                   url=entry.source_url, revision=entry.news.full_content_revision,
                   policy_version=entry.binding.policy_version)
        try:
            source = entry.binding.source_links.filter(enabled=True,
                source__publication__owner='miniflux').order_by('source_id').first()
            if source is None:
                raise OperationError('no_enabled_source')
            refetch_fence(entry, source.source_id, None)
            row.update(source=source.source_id, status='candidate')
        except OperationError as error:
            row.update(status='skipped', reason=error.code)
        rows.append(row)
    return {'version': 1, 'cutoff': cutoff.isoformat(), 'created_at': timezone.now().isoformat(), 'rows': rows}


def outcome(operation):
    result = operation.safe_result
    if operation.state == 'succeeded' and not result.get('pending_sync'):
        return 'success' if result.get('sync_status') in {'accepted', 'unchanged'} else 'failed'
    if operation.state in {'unknown', 'manual_blocked'} or result.get('outcome_unknown'):
        return 'unconfirmed'
    if operation.state in {'failed', 'cancelled'}:
        return 'failed'
    return 'waiting'


@transaction.atomic
def submit(row):
    """Stable key survives lost manifest writes; unknown intents are never resent."""
    key = f"body-repair:{row['entry']}:{row['policy_version']}"
    FeedBinding.objects.filter(pk=row['binding']).update(updated_at=F('updated_at'))
    old = FeedOperation.objects.filter(actor=None, dedupe_key=key).first()
    if old:
        return old
    active = FeedOperation.objects.filter(entry_id=row['entry'], kind='refetch_entry').exclude(
        state__in=['failed', 'cancelled']).exclude(state='succeeded', safe_result__pending_sync=False).first()
    if active:
        raise OperationError('existing_refetch_requires_reconciliation')
    entry = EngineEntryMap.objects.select_related('binding', 'news').get(pk=row['entry'])
    if (str(entry.binding_id) != row['binding'] or entry.news_id != row['news']
            or entry.source_url != row['url'] or entry.binding.policy_version != row['policy_version']
            or entry.news.full_content_revision != row['revision']):
        raise OperationError('preview_stale')
    return enqueue_operation('refetch_entry', actor=None, binding=entry.binding, entry=entry,
                             source_id=row['source'], dedupe_key=key)
