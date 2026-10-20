"""Bounded OPML preview/confirm. Parsing never resolves or fetches feed URLs."""
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
from api.rss.operations import OperationError, canonicalize_feed_url, sqlite_retry
from api.rss.subscriptions import subscribe

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
            # Credential-bearing invalid URLs and their labels are not persisted.
            rows.append(dict(feed_url='', title='无效订阅', groups=[], status='invalid', error_code=exc.code))
            continue
        if url in urls:
            urls[url]['groups'] = sorted(set(urls[url]['groups']) | set(groups))[:100]
            continue
        row = dict(feed_url=url, title=str(feed.get('title', ''))[:255], groups=groups, status='preview')
        rows.append(row)
        urls[url] = row
    return rows


def batch_data(batch):
    items = []
    for item in batch.items.select_related('operation').order_by('pk'):
        state = item.status
        if item.operation_id:
            if item.operation.state == 'succeeded':
                state = 'succeeded'
            elif item.operation.state in {'failed', 'cancelled', 'manual_blocked'}:
                state = 'failed'
        items.append({'id': str(item.pk), 'feed_url': item.feed_url, 'title': item.title,
                      'groups': item.groups, 'group_ids': item.selected_group_ids,
                      'status': state, 'error_code': item.error_code or (item.operation.safe_result.get('code', '') if item.operation_id else ''),
                      'operation_id': str(item.operation_id) if item.operation_id else None,
                      'subscription_id': item.subscription_id})
    return {'id': str(batch.pk), 'status': batch.status, 'expires_at': batch.expires_at,
            'items': items, 'groups': sorted({group for item in items for group in item['groups']})}


@sqlite_retry
@transaction.atomic
def preview(user, raw):
    rows = parse_opml(raw)
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    if RssImportBatch.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 10:
        raise Throttled(detail='导入预览过于频繁，请稍后重试。')
    batch = RssImportBatch.objects.create(user=user, file_hash=sha256(raw).hexdigest(),
                                        expires_at=timezone.now() + timedelta(minutes=30))
    token = signing.dumps({'id': str(batch.pk), 'user': user.pk, 'file_hash': batch.file_hash}, salt=SALT)
    batch.preview_token_hash = sha256(token.encode()).hexdigest()
    batch.save(update_fields=['preview_token_hash'])
    RssImportItem.objects.bulk_create([RssImportItem(batch=batch, **row) for row in rows])
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
        batch = RssImportBatch.objects.get(pk=identity, user=user, file_hash=payload['file_hash'],
            preview_token_hash=sha256(token.encode()).hexdigest())
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
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
    """Durable local intents only. T08 owns physical feed registration/retries."""
    completed = 0
    for identity in list(RssImportItem.objects.filter(status='pending').order_by('updated_at').values_list('pk', flat=True)[:limit]):
        with transaction.atomic():
            RssImportItem.objects.filter(pk=identity).update(updated_at=F('updated_at'))
            item = RssImportItem.objects.select_related('batch__user').get(pk=identity)
            if item.status != 'pending':
                continue
            try:
                # Savepoint lets permanent item failures leave other imports intact.
                with transaction.atomic():
                    if not item.batch.user.is_active:
                        raise ValidationError('账户已停用。')
                    _, result = subscribe(item.batch.user, {'feed_url': item.feed_url, 'group_ids': item.selected_group_ids},
                                          item.batch.options.get('retry_keys', {}).get(str(item.pk), f'opml:{item.batch_id}:{item.pk}'))
            except (APIException, OperationError, Http404) as exc:
                item.status = 'failed'
                item.error_code = exc.code if isinstance(exc, OperationError) else getattr(exc, 'default_code', 'invalid_input')
            else:
                item.status = 'queued'
                item.operation_id = result['operation_id']
                item.subscription_id = result['subscription']['id'] if result['subscription'] else None
            item.save(update_fields=['status', 'error_code', 'operation', 'subscription', 'updated_at'])
            if not item.batch.items.filter(status='pending').exists():
                RssImportBatch.objects.filter(pk=item.batch_id).update(status='complete')
            completed += 1
    return completed


@sqlite_retry
@transaction.atomic
def retry_failed(user, identity, data):
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    try:
        batch = RssImportBatch.objects.get(pk=identity, user=user)
    except RssImportBatch.DoesNotExist:
        raise Http404 from None
    if not isinstance(data, dict) or set(data) != {'selected_ids'} or not isinstance(data['selected_ids'], list) or not 1 <= len(data['selected_ids']) <= MAX_FEEDS:
        raise ValidationError('请选择失败的导入项目。')
    try:
        selected = {str(UUID(value)) for value in data['selected_ids']}
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('项目无效。') from None
    items = list(batch.items.filter(pk__in=selected).select_related('operation'))
    if len(items) != len(selected):
        raise Http404
    retries = dict(batch.options.get('retry_keys', {}))
    for item in items:
        # Unknown outcomes stay gated in the control worker; retries cannot bypass it.
        if item.status == 'pending':
            continue
        if not ((item.status == 'failed' and item.operation_id is None) or
                (item.operation_id and item.operation.state == 'failed')):
            raise RssConflict('只能重试明确失败的项目。')
        if item.operation_id:
            retries[str(item.pk)] = f'opml:{item.batch_id}:{item.pk}:{item.operation_id}'
        item.status, item.error_code, item.operation_id = 'pending', '', None
        item.save(update_fields=['status', 'error_code', 'operation', 'updated_at'])
    batch.options = {**batch.options, 'retry_keys': retries}
    batch.status = 'confirmed'
    batch.save(update_fields=['options', 'status', 'updated_at'])
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
