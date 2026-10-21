"""Shared physical work with independent owner-scoped subscription intents.

Callers reserve SQLite's writer before attach/finish. No network I/O here.
"""
import uuid
import time

from django.db.models import Q
from django.utils import timezone

from api.rss.models import FeedOperation
from api.rss.operations import enqueue_operation, reconcile_binding, unresolved_control_operations

LIVE = ('pending', 'running', 'retry_wait', 'unknown', 'manual_blocked')
_settled = {}


def active_intents(queryset):
    return queryset.filter(actor__is_active=True, state__in=LIVE).filter(
        Q(rssimportitem__isnull=True) | Q(rssimportitem__batch__removed_at__isnull=True,
            rssimportitem__batch__cancelled_at__isnull=True, rssimportitem__batch__paused=False,
            rssimportitem__status__in=['pending', 'queued', 'failed'])).distinct()


def active_waiters(operation):
    return active_intents(operation.subscription_waiters.all())


def binding_ready(binding):
    return (binding.engine_feed_id is not None and binding.desired_enabled
        and binding.connection_state == 'ready'
        and binding.applied_policy_version == binding.policy_version
        and not unresolved_control_operations(binding.pk).exists())


def attach_subscription_work(operation):
    """Attach after durable owner intent holds a collection reference."""
    root = reconcile_binding(operation.binding_id)
    operation.binding.refresh_from_db()
    binding = operation.binding
    if binding_ready(binding):
        from api.rss.subscriptions import complete_subscription
        complete_subscription(operation)
        operation.refresh_from_db()
        if 'subscription' not in operation.safe_input:
            from api.rss.operations import OperationError
            raise OperationError('subscription_intent_changed')
        FeedOperation.objects.filter(pk=operation.pk).update(state='succeeded',
            safe_result={'connected': True}, execution_phase='final_response')
        return 'reused'
    candidates = FeedOperation.objects.filter(binding=binding, actor__isnull=True,
        shared_operation__isnull=True, resolved_at__isnull=True,
        kind__in=['register', 'set_enabled'], state__in=LIVE).order_by('created_at')
    root = candidates.first() or root
    if root is None or root.state in {'failed', 'cancelled', 'succeeded'}:
        root = enqueue_operation('register' if binding.engine_feed_id is None else 'set_enabled',
            actor=None, binding=binding, dedupe_key=f'subscription-work:{binding.pk}:{uuid.uuid4()}')
    reused = root.subscription_waiters.exists()
    FeedOperation.objects.filter(pk=root.pk).update(safe_input={**root.safe_input, 'shared_subscription': True})
    FeedOperation.objects.filter(pk=operation.pk).update(shared_operation=root,
        intent_version=binding.policy_version)
    return 'following' if reused else 'connecting'


def finish_subscription_work(operation):
    """Run inside the physical completion's lease/policy commit transaction."""
    from api.rss.subscriptions import complete_subscription
    from api.rss.operations import OperationError
    from api.rss.control_scheduler import fair_candidates
    identities = fair_candidates(active_waiters(operation), 'actor_id', limit=20, served=_settled)
    for waiter in FeedOperation.objects.filter(pk__in=identities).select_related('actor'):
        _settled[waiter.actor_id] = time.monotonic()
        try:
            complete_subscription(waiter)
        except OperationError:
            pass  # Persist a rejected personal intent below, never lose root facts.
        waiter.refresh_from_db()
        # Invalidated owner/group intents do not become false successes.
        if 'subscription' in waiter.safe_input:
            FeedOperation.objects.filter(pk=waiter.pk).update(state='succeeded',
                safe_result={'connected': True}, execution_phase='final_response',
                next_attempt=None, updated_at=timezone.now())
        else:
            FeedOperation.objects.filter(pk=waiter.pk).update(state='failed',
                safe_result={'code': 'subscription_intent_changed'}, execution_phase='final_response')
            from api.rss.import_models import RssImportItem
            RssImportItem.objects.filter(operation=waiter).exclude(status='removed').update(
                status='failed', outcome='needs_attention', error_code='subscription_intent_changed')


def settle_subscription_work(limit=100):
    """Complete resumed followers of an already-finished physical operation."""
    from django.db import transaction
    from django.db.models import Exists, OuterRef
    from django.db.models import F
    roots = FeedOperation.objects.filter(Q(state='succeeded') | Q(resolved_at__isnull=False),
        binding__desired_enabled=True, binding__connection_state='ready',
        binding__applied_policy_version=F('binding__policy_version')).annotate(
        needs_settlement=Exists(active_intents(FeedOperation.objects.filter(shared_operation_id=OuterRef('pk'))))
        ).filter(needs_settlement=True).order_by('created_at', 'pk').values_list('pk', flat=True)[:limit]
    for identity in list(roots):
        with transaction.atomic():
            FeedOperation.objects.filter(pk=identity).update(updated_at=timezone.now())
            root = FeedOperation.objects.select_related('binding').get(pk=identity)
            if root.binding and binding_ready(root.binding):
                finish_subscription_work(root)
