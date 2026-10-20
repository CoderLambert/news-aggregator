"""Stored public-channel verification and durable, bounded admin submissions.

GET is local/read-only. The shared worker owns all engine I/O and result commits.
An empty legacy POST requests reconciliation only, never permission to create.
"""
from datetime import timedelta
from dataclasses import asdict
from api.rss.review_permissions import review_authority
from hashlib import sha256
import json
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, Count, Exists, F, OuterRef, Q, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from api.models import Source
from api.rss.http import RssAPIView, RssConflict
from api.rss.models import FeedBinding, FeedOperation, FeedVerificationBatch, FeedVerificationItem, SourceFeedLink
from api.rss.operations import OperationError, canonicalize_feed_url, enqueue_operation, sqlite_retry
from api.rss.subscription_views import _key
from api.rss.subscriptions import engine_identity

CONTROL_KINDS = ('register', 'set_enabled', 'update_feed_policy')
ACTIVE = ('pending', 'running', 'retry_wait')
UNCERTAIN = Q(state__in=['unknown', 'manual_blocked']) | Q(safe_result__outcome_unknown=True)
STATUSES = ('unverified', 'verifying', 'passed', 'failed', 'unknown', 'paused')


def source_links(source):
    instance, account = engine_identity()
    return SourceFeedLink.objects.filter(source=source, binding__engine_instance_uuid=instance,
        binding__account_id=account).select_related('binding').order_by('binding_id')


def sources():
    instance, account = engine_identity()
    return Source.objects.filter(publication__publication='public', publication__owner__in=['miniflux', 'paused'],
        feed_links__binding__engine_instance_uuid=instance, feed_links__binding__account_id=account).distinct().select_related('publication')


def public_source(pk):
    return get_object_or_404(sources(), pk=pk)


def safe_feed_url(value):
    try: return canonicalize_feed_url(value,resolve_rsshub=False)
    except OperationError: return ''


def safe_error(value):
    return value if isinstance(value, str) and re.fullmatch('[a-z0-9_]{1,64}', value) else ''


def binding_snapshot(binding):
    """All collection authorities, including publication pause and link changes."""
    return {'instance': str(binding.engine_instance_uuid), 'account': binding.account_id,
        'rsshub': [binding.rsshub_alias,binding.rsshub_gateway_version], 'url': binding.canonical_feed_url, 'effective_url': binding.effective_feed_url, 'feed_id': binding.engine_feed_id,
        'version': binding.policy_version, 'mode': binding.desired_mode, 'enabled': binding.desired_enabled,
        'published_since': binding.published_since.isoformat() if binding.published_since else None,
        'links': list(binding.source_links.order_by('pk').values('pk', 'enabled', 'editorial_pin', 'association_policy',
            'source__publication__publication', 'source__publication__owner', 'source__publication__epoch',
            'source__publication__policy_version', 'source__publication__reading_policy'))}


def operations(binding):
    return FeedOperation.objects.filter(binding=binding, kind__in=CONTROL_KINDS)


def cooldown(binding):
    last = operations(binding).filter(safe_input__admin_recovery__isnull=False).order_by('-created_at').first()
    until = last.created_at + timedelta(seconds=60) if last else None
    return until if until and until > timezone.now() else None


def verification_data(source, *, history=True):
    feeds = []
    for link in source_links(source):
        b = link.binding
        rows = list(operations(b).order_by('-created_at')[:20])
        active = next((o for o in rows if o.state in ACTIVE), None)
        uncertain = operations(b).filter(UNCERTAIN, resolved_at__isnull=True).exclude(state='succeeded').exists()
        latest = rows[0] if rows else None
        paused = source.publication.owner != 'miniflux' or not link.enabled or not b.desired_enabled
        passed = b.engine_feed_id is not None and b.connection_state == 'ready' and b.applied_policy_version == b.policy_version and not uncertain
        status = ('paused' if paused else 'verifying' if active else 'passed' if passed else 'unknown' if uncertain
            else 'failed' if b.connection_state == 'error' or (latest and latest.state == 'failed') else 'unverified')
        until = cooldown(b)
        reason = 'paused' if paused else 'in_progress' if active else 'cooldown' if until else ''
        if latest and latest.state == 'cancelled' and not latest.resolved_at: reason = 'cancelled'
        if link.association_policy != {'version': 1, 'mode': 'all'}: reason = 'unsupported_association_policy'
        try:
            from api.rss.feed_policy import assert_binding_policy
            assert_binding_policy(b, enabled=True)
        except OperationError as exc:
            reason = exc.code

        feed = {'id': str(b.pk), 'feed_url': safe_feed_url(b.canonical_feed_url),
            'effective_feed_url': safe_feed_url(b.effective_feed_url) if b.effective_feed_url else '', 'status': status,
            'policy_version': b.policy_version, 'connection_state': b.connection_state,
            'error_code': safe_error((latest.safe_result.get('code') if latest else '') or b.last_error),
            'operation_state': latest.state if latest else None,
            'execution_phase': latest.execution_phase if latest else 'missing',
            'checked_at': latest.updated_at.isoformat() if latest else None,
            'cooldown_until': until.isoformat() if until else None,
            'can_verify': not reason, 'action_reason': reason,
            'recovery_requires_boundary': uncertain or not rows or any(o.execution_phase == 'missing' for o in rows if not o.resolved_at)}
        if history:
            feed['history'] = [{'id': str(o.pk), 'state': o.state, 'phase': o.execution_phase,
                'attempts': o.attempts, 'error_code': safe_error(o.safe_result.get('code')),
                'created_at': o.created_at.isoformat(), 'updated_at': o.updated_at.isoformat(),
                'resolved_at': o.resolved_at.isoformat() if o.resolved_at else None,
                'resolution': o.resolution.get('reason', ''),
                'recovery_of': str(o.recovery_of_id) if o.recovery_of_id else None} for o in rows]
        feeds.append(feed)
    status = source_status_queryset().filter(pk=source.pk).values_list('verification_status', flat=True).get()
    return {'source_id': source.pk, 'name': source.publication.display_name or source.name,
        'status': status, 'feeds': feeds, 'can_subscribe': status == 'passed' and all(not f['action_reason'] or f['action_reason'] in {'in_progress', 'cooldown'} for f in feeds),
        'can_verify': any(f['can_verify'] for f in feeds), 'pending': status == 'verifying',
        'expected_versions': {f['id']: f['policy_version'] for f in feeds}}


def _request_binding(source, link, actor, key, recover):
    b = link.binding
    FeedBinding.objects.filter(pk=b.pk).update(updated_at=F('updated_at'))
    b.refresh_from_db()
    if (source.publication.owner != 'miniflux' or not link.enabled or not b.desired_enabled
            or link.association_policy != {'version': 1, 'mode': 'all'}):
        return None, 'paused'
    return request_verification(b, actor=actor, key=key, recover=recover, target={'kind':'public_source','id':source.pk})


def request_verification(binding, *, actor, key, recover, target):
    b = binding
    FeedBinding.objects.filter(pk=b.pk).update(updated_at=F('updated_at'))
    b.refresh_from_db()
    from api.rss.feed_policy import assert_binding_policy
    assert_binding_policy(b, enabled=True)
    active = operations(b).filter(state__in=ACTIVE).order_by('created_at').first()
    if active:
        return active, ''
    if cooldown(b):
        return None, 'cooldown'
    previous = list(operations(b).filter(resolved_at__isnull=True).order_by('-created_at'))
    if any(o.state == 'cancelled' for o in previous):
        return None, 'cancelled'
    uncertain = [o for o in previous if o.state in {'unknown', 'manual_blocked'} or o.safe_result.get('outcome_unknown')]
    # An old missing phase is never equivalent to not_sent. A recorded boundary
    # may resolve it, while keeping the old state/error/attempt count intact.
    recorded = bool(previous) or operations(b).filter(resolved_at__isnull=False, resolution__reason='engine_restart').exists()
    safe = recorded and not uncertain and all(o.execution_phase in {'not_sent', 'final_response'}
        and ('admin_recovery' not in o.safe_input or o.safe_input['admin_recovery'].get('allow_create') is True)
        for o in previous)
    allow_create = bool(recover and safe and b.engine_feed_id is None)
    operation = enqueue_operation('register', actor=actor, dedupe_key=key + ':' + str(b.pk), binding=b)
    FeedOperation.objects.filter(pk=operation.pk).update(recovery_of=previous[0] if previous else None,
        safe_input={'admin_recovery': {'allow_create': allow_create, 'snapshot': binding_snapshot(b),
            'source_id': target.get('id') if target['kind'] == 'public_source' else None, 'requested_at': timezone.now().isoformat(),
            'authority': asdict(review_authority(actor))}})
    if target['kind'] == 'public_candidate':
        operation.refresh_from_db()
        inputs = operation.safe_input
        inputs['review_target'] = {'candidate_id': str(target['id']), 'version': target['version'], 'authority': asdict(review_authority(actor))}
        FeedOperation.objects.filter(pk=operation.pk).update(safe_input=inputs)
    return operation, ''


def batch_data(batch):
    items = []
    instance, account = engine_identity()
    unfinished = False
    for item in batch.items.select_related('operation', 'binding', 'source__publication').order_by('pk'):
        # Progress cannot disclose a source moved to personal/another instance.
        if (not item.source_id or item.source.publication.publication != 'public' or not item.binding_id
                or str(item.binding.engine_instance_uuid) != str(instance) or item.binding.account_id != account):
            items.append({'status': 'skipped', 'reason': 'scope_changed'})
            continue
        op = item.operation
        status = item.status
        if op:
            unfinished = unfinished or op.state in (*ACTIVE, 'unknown')
            status = ('completed' if op.state == 'succeeded' else 'unknown' if op.state in {'unknown', 'manual_blocked'}
                else 'failed' if op.state in {'failed', 'cancelled'} else 'running' if op.state == 'running' else 'accepted')
        items.append({'source_id': item.source_id, 'name': item.source.publication.display_name or item.source.name, 'binding_id': str(item.binding_id), 'status': status,
            'reason': item.reason or (safe_error(op.safe_result.get('code')) if op else ''),
            'operation_id': str(op.pk) if op else None})
    counts = {s: sum(i['status'] == s for i in items) for s in ('accepted', 'running', 'unknown', 'skipped', 'failed', 'completed')}
    return {'id': str(batch.pk), 'items': items, 'counts': counts,
        'done': not unfinished}


@sqlite_retry
@transaction.atomic
def submit(targets, actor, key, recover):
    get_user_model().objects.filter(pk=actor.pk).update(last_login=F('last_login'))
    fingerprint = sha256(json.dumps({'targets': targets, 'recover': recover}, sort_keys=True).encode()).hexdigest()
    old = FeedVerificationBatch.objects.filter(actor=actor, dedupe_key=key).first()
    if old:
        if old.request_hash != fingerprint: raise RssConflict(code='idempotency_conflict')
        return old
    prepared = []
    for target in targets:
        source = public_source(target['source_id'])
        links = list(source_links(source))
        versions = target.get('expected_versions')
        if recover and (not isinstance(versions, dict) or versions != {str(l.binding_id): l.binding.policy_version for l in links}
                or any(type(v) is not int for v in versions.values())):
            raise RssConflict('频道策略已改变，请刷新后重试。', code='stale_policy')
        prepared.append((source, links))
    batch = FeedVerificationBatch.objects.create(actor=actor, dedupe_key=key, request_hash=fingerprint, targets=targets)
    for source, links in prepared:
        for link in links:
            try:
                operation, reason = _request_binding(source, link, actor, key, recover)
            except OperationError as error:
                operation, reason = None, error.code
            FeedVerificationItem.objects.create(batch=batch, source=source, binding=link.binding,
                operation=operation, status='skipped' if reason else 'accepted', reason=reason)
    return batch


class AdminRssView(RssAPIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        from api.rss.review_permissions import review_authority
        if review_authority(request.user) is None: raise PermissionDenied('需要频道审核权限。')


class SourceVerificationView(AdminRssView):
    def get(self, request, pk):
        return Response(verification_data(public_source(pk)))

    def post(self, request, pk):
        recover = bool(request.data)
        if recover and (request.data.get('action') != 'verify_and_recover' or set(request.data) != {'action', 'expected_versions'}):
            raise ValidationError('请明确提交核验恢复动作和预期版本。')
        target = {'source_id': pk, **({'expected_versions': request.data['expected_versions']} if recover else {})}
        batch = submit([target], request.user, _key(request, 'verify-source'), recover)
        return Response({**verification_data(public_source(pk)), 'batch_id': str(batch.pk), 'batch': batch_data(batch)}, status=202)


class SourceListView(AdminRssView):
    def post(self, request):
        from api.rss.recommendations import register_public_candidate
        from api.rss.additions import request_key
        return Response(register_public_candidate(request.user, dict(request.data), request_key(request)), status=202)

    def get(self, request):
        try:
            page = int(request.query_params.get('page', '1'))
            size = int(request.query_params.get('page_size', '25'))
            if page < 1 or page > 100000 or size not in (25, 50): raise ValueError
        except (TypeError, ValueError): raise ValidationError('页码须为正整数，每页可选25或50条。')
        status = request.query_params.get('status', 'pending')
        if status not in (*STATUSES, 'pending', 'all'): raise ValidationError('无效的频道状态。')
        q = request.query_params.get('q', '').strip()
        if len(q) > 200: raise ValidationError('搜索内容最多200字符。')
        instance, account = engine_identity()
        qs = source_status_queryset()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(publication__display_name__icontains=q)
                | Q(feed_links__binding__effective_feed_url__icontains=q,
                    feed_links__binding__engine_instance_uuid=instance, feed_links__binding__account_id=account)
                | Q(feed_links__binding__canonical_feed_url__icontains=q,
                    feed_links__binding__engine_instance_uuid=instance, feed_links__binding__account_id=account))
        counts = dict.fromkeys(STATUSES, 0)
        for row in qs.order_by().values('verification_status').annotate(total=Count('pk', distinct=True)):
            counts[row['verification_status']] = row['total']
        counts.update(pending=sum(counts[s] for s in ('unverified', 'failed', 'unknown')), all=sum(counts.values()))
        if status == 'pending': qs = qs.filter(verification_status__in=['unverified', 'failed', 'unknown'])
        elif status != 'all': qs = qs.filter(verification_status=status)
        count = qs.count()
        rows = list(qs.order_by('pk')[(page-1)*size:page*size])
        return Response({'results': [verification_data(s, history=False) for s in rows], 'count': count,
            'counts': counts, 'page': page, 'page_size': size, 'server_time': timezone.now().isoformat()})


class VerificationBatchesView(AdminRssView):
    def post(self, request):
        targets = request.data.get('targets')
        if (set(request.data) != {'action', 'targets'} or request.data.get('action') != 'verify_and_recover'
                or not isinstance(targets, list) or not 1 <= len(targets) <= 50
                or any(not isinstance(t, dict) or set(t) != {'source_id', 'expected_versions'}
                    or type(t['source_id']) is not int or t['source_id'] <= 0 for t in targets)
                or len({t['source_id'] for t in targets}) != len(targets)):
            raise ValidationError('每批须包含1–50个不同频道及预期版本。')
        batch = submit(sorted(targets, key=lambda t: t['source_id']), request.user, _key(request, 'verify-batch'), True)
        return Response(batch_data(batch), status=202)


class VerificationBatchView(AdminRssView):
    def get(self, request, pk):
        return Response(batch_data(get_object_or_404(FeedVerificationBatch, pk=pk, actor=request.user)))


@sqlite_retry
@transaction.atomic
def record_restart_boundary(instance, account, evidence):
    """Maintenance-only receipt, produced after stopping the dedicated controller
    and observing the SAME engine container start again. Never callable via HTTP.
    Last dispatch/update, not operation creation time, must precede the stop.
    """
    from datetime import datetime
    if set(evidence) != {'worker_container', 'engine_container', 'worker_stopped_at', 'engine_previous_start', 'engine_started_at'}:
        raise ValueError('invalid_restart_evidence')
    if any(not re.fullmatch('[a-f0-9]{64}', evidence[k]) for k in ('worker_container', 'engine_container')):
        raise ValueError('invalid_restart_evidence')
    stopped, previous, started = [datetime.fromisoformat(evidence[k].replace('Z', '+00:00'))
        for k in ('worker_stopped_at', 'engine_previous_start', 'engine_started_at')]
    if any(v.tzinfo is None for v in (stopped, previous, started)) or not previous < stopped < started:
        raise ValueError('invalid_restart_order')
    FeedBinding.objects.filter(engine_instance_uuid=instance, account_id=account).update(updated_at=F('updated_at'))
    candidates = FeedOperation.objects.filter(binding__engine_instance_uuid=instance, binding__account_id=account,
        kind__in=CONTROL_KINDS, resolved_at__isnull=True, updated_at__lte=stopped).filter(
            Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=stopped)).exclude(state__in=['succeeded', 'cancelled'])
    total = 0
    for operation in candidates:
        if operation.state in ACTIVE and operation.execution_phase == 'not_sent':
            continue
        fields = {'resolved_at': timezone.now(), 'resolution': {'reason': 'engine_restart', **evidence},
            'lease_epoch': F('lease_epoch')+1, 'lease_token': None, 'lease_until': None, 'next_attempt': None}
        if operation.state in (*ACTIVE, 'unknown'):
            fields['state'] = 'manual_blocked'
        FeedOperation.objects.filter(pk=operation.pk).update(**fields)
        total += 1
    return total


def source_status_queryset():
    instance, account = engine_identity()
    links = SourceFeedLink.objects.filter(source_id=OuterRef('pk'), binding__engine_instance_uuid=instance,
        binding__account_id=account)
    ops = FeedOperation.objects.filter(binding_id=OuterRef('binding_id'), kind__in=CONTROL_KINDS)
    # Latest failure matters only while the binding is not currently confirmed.
    from django.db.models import Subquery
    links = links.annotate(_active=Exists(ops.filter(state__in=ACTIVE)),
        _unknown=Exists(ops.filter(UNCERTAIN, resolved_at__isnull=True).exclude(state='succeeded')),
        _latest=Subquery(ops.order_by('-created_at').values('state')[:1]),
    ).annotate(_status=Case(
        When(Q(enabled=False) | Q(binding__desired_enabled=False), then=Value('paused')),
        When(_active=True, then=Value('verifying')), When(_unknown=True, then=Value('unknown')),
        When(binding__engine_feed_id__isnull=False, binding__connection_state='ready',
            binding__applied_policy_version=F('binding__policy_version'), then=Value('passed')),
        When(Q(binding__connection_state='error') | Q(_latest='failed'), then=Value('failed')),
        default=Value('unverified')))
    qs = sources().annotate(**{'_has_'+status: Exists(links.filter(_status=status)) for status in STATUSES})
    return qs.annotate(verification_status=Case(
        When(publication__owner='paused', then=Value('paused')),
        *[When(**{'_has_'+status: True, 'then': Value(status)})
            for status in ('verifying', 'unknown', 'failed', 'unverified', 'paused', 'passed')],
        default=Value('paused')))
