"""Bounded OPML preview/confirm. Parsing never resolves or fetches feed URLs."""
from collections import Counter
from datetime import timedelta
from hashlib import sha256
import json
from uuid import UUID
from xml.etree import ElementTree as ET

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException, Throttled, ValidationError

from api.models import ChannelGroup, ChannelSubscription
from api.rss.http import RssConflict
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.operations import OperationError, cancel_operation, canonicalize_feed_url, sqlite_retry
from api.rss.subscriptions import unsubscribe
from api.rss.models import FeedOperation

SALT = 'rss-opml-v1'
MAX_BYTES = 1024 * 1024
MAX_FEEDS = 500


class TooLarge(APIException):
    status_code = 413
    default_detail = 'OPML 文件超过允许大小。'
    default_code = 'too_large'


def parse_opml(raw):
    # Imports stay local: the lightweight sync worker never imports XML libraries.
    from defusedxml.ElementTree import fromstring
    from defusedxml.common import DefusedXmlException
    import listparser
    if not isinstance(raw, bytes) or not raw:
        raise ValidationError('请选择 OPML 文件。')
    if len(raw) > MAX_BYTES:
        raise TooLarge
    try:
        root = fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, ValueError):
        raise ValidationError('OPML XML 无效或包含不允许的实体。') from None
    if root.tag != 'opml':
        raise ValidationError('文件须为 OPML。')
    pending, count = [(root, 0)], 0
    while pending:
        element, depth = pending.pop()
        count += 1
        if depth > 16 or count > 10000:
            raise TooLarge
        pending.extend((child, depth + 1) for child in element)
    # bytes is deliberate: listparser's string overload can issue HTTP requests.
    feeds = listparser.parse(raw).get('feeds', [])
    if not feeds or len(feeds) > MAX_FEEDS:
        raise ValidationError('OPML 须包含1–500个订阅。')
    rows, urls = [], {}
    for feed in feeds:
        groups = sorted({' / '.join(path)[:160] for path in feed.get('categories', []) if path})[:100]
        try:
            url = canonicalize_feed_url(feed.get('url', ''))
        except OperationError as exc:
            # Keep credential-bearing invalid URLs and labels out of parsed rows/DTOs.
            rows.append(dict(feed_url='', title='无效订阅', groups=[], status='invalid', error_code=exc.code))
            continue
        if url in urls:
            urls[url]['groups'] = sorted(set(urls[url]['groups']) | set(groups))[:100]
            urls[url]['duplicate_count'] += 1
            continue
        row = dict(feed_url=url, title=str(feed.get('title', ''))[:255], groups=groups, status='preview', duplicate_count=0)
        rows.append(row)
        urls[url] = row
    return rows


def batch_data(batch, *, include_items=True):
    items = []
    classifications = {}
    if batch.status == 'preview':
        from api.rss.import_scheduler import classify_imports
        classifications = classify_imports(batch.user, set(batch.items.values_list('feed_url', flat=True)))
    for item in batch.items.select_related('operation__shared_operation').order_by('pk'):
        operation = item.operation
        work = (operation.shared_operation or operation) if operation else None
        outcome = classifications.get(item.feed_url, item.outcome or 'waiting')
        next_attempt = item.next_attempt
        can_retry = False
        state = item.status
        if (state == 'failed' and item.error_code == 'throttled' and not item.operation_id
                and batch.confirmed_request_hash and not batch.removed_at):
            state = 'pending'
        if operation and item.status != 'removed':
            if operation.state == 'succeeded':
                state = 'succeeded'
                if outcome not in {'already_subscribed', 'reused'}:
                    outcome = 'connected'
            elif operation.state == 'cancelled':
                state, outcome = 'removed', 'cancelled'
            elif work.state in {'failed', 'cancelled', 'manual_blocked'}:
                state, outcome = 'failed', 'needs_attention'
                can_retry = work.state == 'failed' and not work.safe_result.get('outcome_unknown')
            elif work.state == 'succeeded' and operation.state in {'pending', 'retry_wait', 'unknown', 'manual_blocked'}:
                state, outcome = 'queued', 'waiting'
            elif work.state == 'unknown':
                state, outcome = 'queued', 'checking'
            elif work.state == 'retry_wait':
                state, outcome = 'queued', 'retry_wait'
            elif work.state == 'running':
                state, outcome = 'queued', 'connecting'
            next_attempt = work.next_attempt
        elif state == 'failed':
            can_retry = True
        if state == 'invalid':
            outcome = 'invalid'
        if batch.paused and state in {'pending', 'queued'}:
            outcome = 'paused'
        items.append({'id': str(item.pk), 'feed_url': item.feed_url, 'title': item.title,
                      'groups': item.groups, 'group_ids': item.selected_group_ids,
                      'status': state, 'error_code': item.error_code or (work.safe_result.get('code', '') if work else ''),
                      'outcome': outcome, 'next_attempt': next_attempt, 'can_retry': can_retry,
                      'duplicate_count': item.duplicate_count,
                      'operation_id': str(item.operation_id) if item.operation_id else None,
                      'subscription_id': item.subscription_id})
    result = {'id': str(batch.pk), 'status': batch.status, 'expires_at': batch.expires_at,
              'filename': batch.filename, 'file_size': batch.file_size,
              'file_available': bool(batch.file_size), 'created_at': batch.created_at,
              'removed_at': batch.removed_at, 'removed_count': batch.removed_count,
              'paused': batch.paused, 'cancelled_at': batch.cancelled_at,
              'duplicate_count': sum(item['duplicate_count'] for item in items),
              'outcomes': dict(Counter(item['outcome'] for item in items)),
              'counts': dict(Counter(item['status'] for item in items)), 'total': len(items)}
    if include_items:
        result.update(items=items, groups=sorted({group for item in items for group in item['groups']}))
    return result


@sqlite_retry
@transaction.atomic
def preview(user, raw, filename='subscriptions.opml'):
    rows = parse_opml(raw)
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    if RssImportBatch.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 10:
        raise Throttled(detail='导入预览过于频繁，请稍后重试。')
    filename = ''.join(c for c in str(filename).replace('\\', '/').rsplit('/', 1)[-1] if c.isprintable())[:255] or 'subscriptions.opml'
    batch = RssImportBatch.objects.create(user=user, filename=filename, file_content=raw,
                                        file_size=len(raw), file_hash=sha256(raw).hexdigest(),
                                        expires_at=timezone.now() + timedelta(minutes=30))
    token = signing.dumps({'id': str(batch.pk), 'user': user.pk, 'file_hash': batch.file_hash}, salt=SALT)
    batch.preview_token_hash = sha256(token.encode()).hexdigest()
    batch.save(update_fields=['preview_token_hash'])
    from api.rss.import_scheduler import classify_imports
    known = classify_imports(user, {row['feed_url'] for row in rows})
    RssImportItem.objects.bulk_create([RssImportItem(batch=batch, outcome=known.get(row['feed_url'], ''), **row) for row in rows])
    return {**batch_data(batch), 'preview_token': token}


@sqlite_retry
@transaction.atomic
def confirm(user, data):
    if not isinstance(data, dict) or set(data) != {'preview_token', 'selected_ids', 'group_map'}:
        raise ValidationError('请提交预览凭据、所选项目与分组映射。')
    token = data['preview_token']
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        payload = signing.loads(token, salt=SALT, max_age=1800)
        identity = UUID(payload['id'])
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise ValidationError('预览已过期或无效。') from None
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    try:
        batch = RssImportBatch.objects.defer('file_content').get(pk=identity, user=user, file_hash=payload['file_hash'],
            preview_token_hash=sha256(token.encode()).hexdigest())
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
    if batch.removed_at:
        raise RssConflict('此批次已移除，不能重新导入。')
    if payload['user'] != user.pk or batch.expires_at <= timezone.now():
        raise ValidationError('预览已过期或无效。')
    selected, mapping = data['selected_ids'], data['group_map']
    if not isinstance(selected, list) or not selected or len(selected) > MAX_FEEDS or not isinstance(mapping, dict):
        raise ValidationError('请选择有效订阅与分组。')
    try:
        selected = sorted({str(UUID(value)) for value in selected})
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('无效的所选项目。') from None
    items = list(batch.items.filter(pk__in=selected))
    if len(items) != len(selected) or any(not item.feed_url or item.status == 'invalid' for item in items):
        raise ValidationError('所选项目不属于此有效预览。')
    known_groups = {group for item in batch.items.all() for group in item.groups}
    if set(mapping) - known_groups:
        raise ValidationError('分组不属于此预览。')
    normalized = {}
    for label, value in mapping.items():
        if value is None or type(value) is int and value > 0:
            normalized[label] = value
        elif isinstance(value, dict) and set(value) == {'create'} and isinstance(value['create'], str) and 1 <= len(value['create'].strip()) <= 40:
            normalized[label] = {'create': value['create'].strip()}
        else:
            raise ValidationError('分组映射须为自己的分组ID、新分组名称或空值。')
    digest = sha256(json.dumps({'selected': selected, 'groups': normalized}, sort_keys=True).encode()).hexdigest()
    if batch.confirmed_request_hash:
        if batch.confirmed_request_hash != digest:
            raise RssConflict('已确认的导入不能改变选择。', code='idempotency_conflict')
        return batch_data(batch)
    resolved = {}
    for label, value in normalized.items():
        if value is None:
            continue
        if isinstance(value, dict):
            group, _ = ChannelGroup.objects.get_or_create(user=user, name=value['create'])
        else:
            try:
                group = ChannelGroup.objects.get(user=user, pk=value)
            except ChannelGroup.DoesNotExist:
                raise Http404 from None
        resolved[label] = group.pk
    for item in items:
        item.selected_group_ids = sorted({resolved[label] for label in item.groups if label in resolved})
        item.status = 'pending'
    RssImportItem.objects.bulk_update(items, ['selected_group_ids', 'status'])
    batch.confirmed_request_hash, batch.status = digest, 'confirmed'
    batch.options = {'selected_ids': selected, 'group_map': resolved}
    batch.save(update_fields=['confirmed_request_hash', 'status', 'options', 'updated_at'])
    return batch_data(batch)


def process_imports(limit=10):
    from api.rss.import_scheduler import process_imports as schedule
    return schedule(limit=limit)


@sqlite_retry
@transaction.atomic
def retry_failed(user, identity, data):
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    try:
        batch = RssImportBatch.objects.defer('file_content').get(pk=identity, user=user)
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
    if batch.removed_at or batch.cancelled_at:
        raise RssConflict('此批次已停止，不能重试。')
    if not isinstance(data, dict) or set(data) != {'selected_ids'} or not isinstance(data['selected_ids'], list) or not 1 <= len(data['selected_ids']) <= MAX_FEEDS:
        raise ValidationError('请选择失败的导入项目。')
    try:
        selected = {str(UUID(value)) for value in data['selected_ids']}
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('项目无效。') from None
    items = list(batch.items.filter(pk__in=selected).select_related('operation__shared_operation'))
    if len(items) != len(selected):
        raise Http404
    retries = dict(batch.options.get('retry_keys', {}))
    for item in items:
        # Unknown outcomes stay gated in the control worker; retries cannot bypass it.
        if item.status == 'pending':
            continue
        work = (item.operation.shared_operation or item.operation) if item.operation_id else None
        if not ((item.status == 'failed' and work is None) or
                (work and work.state == 'failed' and not work.safe_result.get('outcome_unknown'))):
            raise RssConflict('只能重试明确失败的项目。')
        if item.operation_id:
            retries[str(item.pk)] = f'opml:{item.batch_id}:{item.pk}:{item.operation_id}'
            cancel_operation(user, item.operation_id)
        item.status, item.error_code, item.operation_id = 'pending', '', None
        item.outcome, item.next_attempt = 'waiting', None
        item.save(update_fields=['status', 'error_code', 'operation', 'outcome', 'next_attempt', 'updated_at'])
    batch.options = {**batch.options, 'retry_keys': retries}
    batch.status = 'confirmed'
    batch.save(update_fields=['options', 'status', 'updated_at'])
    return batch_data(batch)


@sqlite_retry
@transaction.atomic
def remove_batch(user, identity):
    # Serialize against import processing and worker completion before reading
    # provenance. Cancellation fences leases before any relationship is removed.
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    try:
        batch = RssImportBatch.objects.defer('file_content').get(pk=identity, user=user)
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
    if batch.removed_at:
        return batch_data(batch)
    batch.removed_at = timezone.now()
    batch.status = 'removed'
    batch.save(update_fields=['removed_at', 'status', 'updated_at'])
    items = list(batch.items.all())
    for item in items:
        if item.operation_id and not RssImportItem.objects.filter(operation_id=item.operation_id,
                batch__removed_at__isnull=True, batch__cancelled_at__isnull=True).exclude(batch=batch).exists():
            cancel_operation(user, item.operation_id)
    # An FK cleared by an earlier unsubscribe cannot target a later subscription
    # to the same source. Old batches default to unproven and remove nothing.
    subscription_ids = {item.subscription_id for item in items
                        if item.created_subscription and item.subscription_id}
    owned = list(ChannelSubscription.objects.filter(user=user, pk__in=subscription_ids).values_list('pk', flat=True))
    for identity in owned:
        unsubscribe(user, identity)
    batch.removed_count = len(owned)
    batch.save(update_fields=['removed_count'])
    batch.items.exclude(status__in=['invalid', 'preview']).update(status='removed')
    return batch_data(batch)


@sqlite_retry
@transaction.atomic
def control_batch(user, identity, data):
    if not isinstance(data, dict) or set(data) != {'action'} or data['action'] not in {'pause', 'resume', 'cancel'}:
        raise ValidationError('请选择暂停、继续或取消剩余任务。')
    if not get_user_model().objects.filter(pk=user.pk, is_active=True).update(last_login=F('last_login')):
        raise Http404
    try:
        batch = RssImportBatch.objects.defer('file_content').get(pk=identity, user=user)
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
    if batch.removed_at or batch.status == 'preview':
        raise RssConflict('此批次当前不能执行该操作。')
    if batch.cancelled_at:
        if data['action'] == 'cancel':
            return batch_data(batch)
        raise RssConflict('已取消的批次不能继续，请重新导入。')
    if data['action'] == 'cancel':
        batch.cancelled_at, batch.paused = timezone.now(), False
        batch.save(update_fields=['cancelled_at', 'paused', 'updated_at'])
        unfinished = list(batch.items.filter(status__in=['pending', 'queued', 'failed']).select_related('operation'))
        for item in unfinished:
            if item.operation_id and not RssImportItem.objects.filter(operation_id=item.operation_id,
                    batch__removed_at__isnull=True, batch__cancelled_at__isnull=True).exists():
                cancel_operation(user, item.operation_id)
        batch.items.filter(pk__in=[item.pk for item in unfinished]).update(status='removed', outcome='cancelled', error_code='')
    else:
        batch.paused = data['action'] == 'pause'
        batch.save(update_fields=['paused', 'updated_at'])
    return batch_data(batch)


def export_opml(user):
    root = ET.Element('opml', version='2.0')
    ET.SubElement(ET.SubElement(root, 'head'), 'title').text = '我的订阅'
    body = ET.SubElement(root, 'body')
    groups = {}
    for subscription in ChannelSubscription.objects.filter(user=user).select_related('source__publication').prefetch_related('groups', 'source__feed_links__binding'):
        labels = list(subscription.groups.values_list('name', flat=True)) or [None]
        urls = [link.binding.rsshub_alias or link.binding.canonical_feed_url for link in subscription.source.feed_links.all()]
        if not urls:
            from api.services.source_policy import policy_for_name
            policy = policy_for_name(subscription.source.name)
            if policy and policy.feed_url:
                urls.append(policy.feed_url)
        for feed_url in dict.fromkeys(urls):
            try:
                if feed_url.startswith('rsshub://'):
                    from api.rss.rsshub_url import normalize_alias
                    url=normalize_alias(feed_url)
                else:
                    url = canonicalize_feed_url(feed_url,resolve_rsshub=False)
            except ValueError:
                continue
            for label in labels:
                parent = body
                if label:
                    if label not in groups:
                        groups[label] = ET.SubElement(body, 'outline', text=label, title=label)
                    parent = groups[label]
                name = subscription.source.publication.display_name or subscription.source.name
                ET.SubElement(parent, 'outline', type='rss', text=name, title=name, xmlUrl=url)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
