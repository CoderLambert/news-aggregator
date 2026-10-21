"""Owner-fair OPML admission and read-only duplicate classification."""
from datetime import timedelta
import time

from django.db import transaction
from django.db.models import F, Q, Prefetch
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException, Throttled

from api.rss.control_scheduler import fair_candidates
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.models import FeedBinding
from api.rss.operations import OperationError, sqlite_retry
from api.rss.subscriptions import engine_identity, subscribe

_served = {}


def classify_imports(user, urls):
    """Batch lookup; classify only URLs supplied by this owner, never reveal actors."""
    from api.rss.subscriptions import EngineUnavailable
    from api.models import ChannelSubscription
    try:
        instance, account = engine_identity()
    except EngineUnavailable:
        return {}
    bindings = FeedBinding.objects.filter(engine_instance_uuid=instance, account_id=account).filter(
        Q(canonical_feed_url__in=urls) | Q(effective_feed_url__in=urls)).prefetch_related(
            'source_links__source__publication', Prefetch('source_links__source__channel_subscriptions',
                queryset=ChannelSubscription.objects.filter(user=user), to_attr='viewer_subscriptions'))
    result = {}
    for binding in bindings:
        links = [link for link in binding.source_links.all() if link.association_policy == {'version': 1, 'mode': 'all'}]
        subscribed = any(subscription.user_id == user.pk for link in links
            for subscription in link.source.viewer_subscriptions)
        state = 'already_subscribed' if subscribed else ('reused' if binding.connection_state == 'ready'
            and binding.applied_policy_version == binding.policy_version and binding.engine_feed_id else 'following')
        for url in (binding.canonical_feed_url, binding.effective_feed_url):
            if url in urls:
                result[url] = state
    return result


@sqlite_retry
def process_imports(limit=10):
    from api.rss.subscription_work import settle_subscription_work
    settle_subscription_work(limit=limit)
    now = timezone.now()
    recoverable = RssImportItem.objects.filter(status='failed', error_code='throttled', operation__isnull=True,
        batch__status__in=['confirmed', 'complete'], batch__removed_at__isnull=True,
        batch__cancelled_at__isnull=True, batch__user__is_active=True).exclude(batch__confirmed_request_hash='')
    recoverable.filter(pk__in=list(recoverable.order_by('updated_at').values_list('pk', flat=True)[:limit])).update(
        status='pending', updated_at=now)
    due = RssImportItem.objects.filter(status='pending', batch__removed_at__isnull=True,
        batch__cancelled_at__isnull=True, batch__paused=False, batch__user__is_active=True).exclude(
            batch__confirmed_request_hash='').filter(Q(next_attempt__isnull=True) | Q(next_attempt__lte=now))
    processed = 0
    for identity in fair_candidates(due, 'batch__user_id', limit=limit, served=_served,
            order=('updated_at', 'pk')):
        with transaction.atomic():
            RssImportItem.objects.filter(pk=identity).update(updated_at=F('updated_at'))
            item = RssImportItem.objects.select_related('batch__user').defer('batch__file_content').get(pk=identity)
            if item.status != 'pending' or item.batch.removed_at or item.batch.cancelled_at or item.batch.paused:
                continue
            try:
                with transaction.atomic():
                    _, result = subscribe(item.batch.user, {'feed_url': item.feed_url, 'group_ids': item.selected_group_ids},
                        item.batch.options.get('retry_keys', {}).get(str(item.pk), f'opml:{item.batch_id}:{item.pk}'),
                        bulk_import=True)
            except Throttled as exc:
                code = getattr(exc.detail, 'code', 'throttled')
                item.status = 'failed' if code == 'subscription_limit' else 'pending'
                item.error_code = code
                item.outcome = 'needs_attention' if code == 'subscription_limit' else 'waiting'
                item.next_attempt = None if code == 'subscription_limit' else now + timedelta(seconds=max(float(exc.wait or 1), 1))
            except (APIException, OperationError, Http404) as exc:
                temporary = isinstance(exc, APIException) and exc.status_code >= 500 and now - item.batch.created_at < timedelta(hours=24)
                item.status, item.outcome = ('pending', 'retry_wait') if temporary else ('failed', 'needs_attention')
                item.next_attempt = now + timedelta(seconds=30) if temporary else None
                item.error_code = exc.code if isinstance(exc, OperationError) else getattr(exc, 'default_code', 'invalid_input')
            else:
                from api.rss.models import FeedOperation
                item.operation_id = result['operation_id']
                operation = FeedOperation.objects.get(pk=item.operation_id)
                item.status = 'succeeded' if operation.state == 'succeeded' else 'queued'
                item.outcome = result.get('outcome', operation.safe_result.get('outcome', 'connecting'))
                item.error_code, item.next_attempt = '', None
                item.subscription_id = result['subscription']['id'] if result['subscription'] else None
                item.created_subscription = operation.safe_input.get('subscription', {}).get('created_by_operation', False)
            item.save(update_fields=['status', 'outcome', 'error_code', 'next_attempt', 'operation',
                'subscription', 'created_subscription', 'updated_at'])
            _served[item.batch.user_id] = time.monotonic()
            processed += 1
    # Completion reflects terminal work, not merely successful admission.
    for batch_id in RssImportBatch.objects.filter(status='confirmed', removed_at__isnull=True,
            paused=False, cancelled_at__isnull=True).values_list('pk', flat=True)[:100]:
        if not RssImportItem.objects.filter(batch_id=batch_id, status__in=['pending', 'queued']).exists():
            RssImportBatch.objects.filter(pk=batch_id).update(status='complete')
    return processed
