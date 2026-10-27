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

from api.models import ChannelGroup, ChannelGroupRoot, ChannelSubscription
from api.services.channel_grouping import record_group_structure_change
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


class FeedLimitExceeded(APIException):
    status_code = 400
    default_detail = '个人 OPML 每次最多500个订阅。502项公共目录不是个人订阅，请拆分文件或在目录中按需选择；账号订阅上限不变。'
    default_code = 'feed_limit_exceeded'


_GROUP_PATH_PREFIX = 'opml-path:'
_GROUP_LABEL_PREFIX = 'opml-label:'


def _group_path_key(path):
    parts = tuple(str(part)[:160] for part in path if str(part))
    if len(parts) == 1 and not parts[0].startswith((_GROUP_PATH_PREFIX, _GROUP_LABEL_PREFIX)):
        return parts[0]
    if len(parts) == 1:
        return _GROUP_LABEL_PREFIX + json.dumps(parts[0], ensure_ascii=False, separators=(',', ':'))
    return _GROUP_PATH_PREFIX + json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def _group_path_parts(key):
    try:
        if key.startswith(_GROUP_PATH_PREFIX):
            value = json.loads(key[len(_GROUP_PATH_PREFIX):])
            if isinstance(value, list) and value and all(isinstance(part, str) and part for part in value):
                return tuple(value)
        elif key.startswith(_GROUP_LABEL_PREFIX):
            value = json.loads(key[len(_GROUP_LABEL_PREFIX):])
            if isinstance(value, str) and value:
                return (value,)
    except (json.JSONDecodeError, TypeError):
        pass
    return (key,)


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
    if len(feeds) > MAX_FEEDS:
        raise FeedLimitExceeded
    if not feeds:
        raise ValidationError('OPML 须包含1–500个订阅。')
    rows, urls = [], {}
    for feed in feeds:
        groups = sorted({_group_path_key(path) for path in feed.get('categories', []) if path})[:100]
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
                      'subscription_id': item.subscription_id,
                      'can_organize': bool(str(item.pk) in batch.options.get('organizable_item_ids', []) and item.groups)})
    result = {'id': str(batch.pk), 'status': batch.status, 'expires_at': batch.expires_at,
              'filename': batch.filename, 'file_size': batch.file_size,
              'file_available': bool(batch.file_size), 'created_at': batch.created_at,
              'removed_at': batch.removed_at, 'removed_count': batch.removed_count,
              'paused': batch.paused, 'cancelled_at': batch.cancelled_at,
              'duplicate_count': sum(item['duplicate_count'] for item in items),
              'outcomes': dict(Counter(item['outcome'] for item in items)),
              'counts': dict(Counter(item['status'] for item in items)), 'total': len(items)}
    if include_items:
        labels = sorted({group for item in items for group in item['groups']})
        group_paths = {key: _group_path_parts(key) for key in labels}
        owned_paths = {
            _group_path_key((group.root.name, group.name)): group.pk
            for group in ChannelGroup.objects.filter(
                user=batch.user,
            ).select_related('root')
        }
        result.update(
            items=items,
            groups=labels,
            group_labels={key: ' / '.join(group_paths[key]) for key in labels},
            group_names={key: group_paths[key][-1] for key in labels},
            group_matches={key: owned_paths[key] for key in labels if key in owned_paths},
            group_plan=batch.options.get('group_plan', {}),
            organize_existing=batch.options.get('organize_existing', False),
            organization_only=batch.options.get('organization_only', False),
        )
    return result


@sqlite_retry
@transaction.atomic
def preview(user, raw, filename='subscriptions.opml', *, organize_existing=False, organization_only=False):
    from api.rss.opml_grouping import prepare_rows, group_plan, grouping_snapshot
    rows = [] if organization_only else parse_opml(raw)
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    if RssImportBatch.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 10:
        raise Throttled(detail='导入预览过于频繁，请稍后重试。')
    rows = prepare_rows(user, rows, organize_existing=organize_existing)
    if not rows:
        raise ValidationError('没有可预览的已有未分组订阅。')
    organizable_ids = list(ChannelSubscription.objects.filter(user=user, groups__isnull=True).values_list('pk', flat=True)) if organize_existing else []
    options = {'organize_existing': organize_existing, 'organization_only': organization_only,
               'grouping_snapshot': grouping_snapshot(user),
               'group_plan': group_plan(user, {label for row in rows for label in row['groups']})}
    filename = ''.join(c for c in str(filename).replace('\\', '/').rsplit('/', 1)[-1] if c.isprintable())[:255] or 'subscriptions.opml'
    batch = RssImportBatch.objects.create(user=user, filename=filename, file_content=raw,
                                        file_size=len(raw), file_hash=sha256(raw).hexdigest(),
                                        expires_at=timezone.now() + timedelta(minutes=30), options=options)
    token = signing.dumps({'id': str(batch.pk), 'user': user.pk, 'file_hash': batch.file_hash}, salt=SALT)
    batch.preview_token_hash = sha256(token.encode()).hexdigest()
    batch.save(update_fields=['preview_token_hash'])
    from api.rss.import_scheduler import classify_imports
    known = classify_imports(user, {row['feed_url'] for row in rows})
    for row in rows:
        row.setdefault('outcome', known.get(row['feed_url'], ''))
    import_items = [RssImportItem(batch=batch, **row) for row in rows]
    RssImportItem.objects.bulk_create(import_items)
    batch.options = {**options,
        'existing_item_ids': [str(item.pk) for item in import_items if item.subscription_id],
        'organizable_item_ids': [str(item.pk) for item in import_items if item.subscription_id in organizable_ids],
    }
    batch.save(update_fields=['options'])
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
    if not isinstance(selected, list) or not selected or len(selected) > MAX_FEEDS * 2 or not isinstance(mapping, dict):
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
    existing_item_ids = set(batch.options.get('existing_item_ids', []))
    organizable_item_ids = set(batch.options.get('organizable_item_ids', []))
    selected_labels = {label for item in items for label in item.groups
                       if str(item.pk) not in existing_item_ids or str(item.pk) in organizable_item_ids}
    normalized = {}
    for label, value in mapping.items():
        if label not in selected_labels:
            continue
        if value == 'auto' or value is None or type(value) is int and value > 0:
            normalized[label] = value
        elif (isinstance(value, dict) and set(value) == {'create', 'root_id'}
                and isinstance(value['create'], str)
                and 1 <= len(value['create'].strip()) <= 40
                and type(value['root_id']) is int and value['root_id'] > 0):
            name = value['create'].strip()
            if any(ord(character) < 32 or ord(character) == 127 for character in name):
                raise ValidationError('新子分组名称不能包含控制字符。')
            normalized[label] = {'create': name, 'root_id': value['root_id']}
        else:
            raise ValidationError('分组映射须为自己的子分组ID、带根分类的新子分组或空值。')
    for item in items:
        selected_groups = {
            ('new', value['root_id'], value['create']) if isinstance(value, dict) else
            ('auto', batch.options.get('group_plan', {}).get(label, {}).get('name', label)) if value == 'auto' else ('existing', value)
            for label in item.groups
            if (value := normalized.get(label)) is not None
        }
        if len(selected_groups) > 3:
            raise ValidationError('每个频道最多属于三个子分组。')
    digest = sha256(json.dumps({'selected': selected, 'groups': normalized}, sort_keys=True).encode()).hexdigest()
    if batch.confirmed_request_hash:
        if batch.confirmed_request_hash != digest:
            raise RssConflict('已确认的导入不能改变选择。', code='idempotency_conflict')
        return batch_data(batch)
    from api.rss.opml_grouping import grouping_snapshot, resolve_auto_groups, apply_existing_groups
    if ('auto' in normalized.values() or batch.options.get('organize_existing')) and (
            batch.options.get('grouping_snapshot') != grouping_snapshot(user)):
        raise RssConflict('订阅、分组或目录快照已变化，请重新预览。')
    auto_labels = {label for label, value in normalized.items() if value == 'auto'}
    auto_resolved = resolve_auto_groups(user, auto_labels, batch.options.get('group_plan', {}))
    root_ids = {
        value['root_id'] for value in normalized.values() if isinstance(value, dict)
    }
    roots = {
        root.pk: root for root in ChannelGroupRoot.objects.filter(
            user=user, pk__in=root_ids,
        )
    }
    if set(roots) != root_ids:
        raise Http404
    requested_children = {}
    for value in normalized.values():
        if not isinstance(value, dict):
            continue
        prior_root_id = requested_children.setdefault(value['create'], value['root_id'])
        if prior_root_id != value['root_id']:
            raise ValidationError('同名子分组不能映射到不同根分类。')
    if ChannelGroup.objects.filter(user=user).count() + len(requested_children) > 200:
        raise ValidationError('每个账号最多创建 200 个子分组。')
    if ChannelGroup.objects.filter(user=user, name__in=requested_children).exists():
        raise RssConflict('已有同名子分组，请选择其数字 ID。')

    resolved = dict(auto_resolved)
    created_groups = {}
    touched_roots = set()
    for label, value in normalized.items():
        if value is None or value == 'auto':
            continue
        if isinstance(value, dict):
            group = created_groups.get(value['create'])
            if group is None:
                group = ChannelGroup.objects.create(
                    user=user, root=roots[value['root_id']], name=value['create'],
                )
                created_groups[value['create']] = group
                touched_roots.add(group.root_id)
        else:
            try:
                group = ChannelGroup.objects.get(user=user, pk=value)
            except ChannelGroup.DoesNotExist:
                raise Http404 from None
        resolved[label] = group.pk
    if touched_roots:
        record_group_structure_change(user, root_ids=touched_roots)
    for item in items:
        item.selected_group_ids = sorted({resolved[label] for label in item.groups if label in resolved})
        if str(item.pk) in existing_item_ids:
            if not item.subscription_id:
                raise RssConflict('原订阅已移除，请重新预览。')
            item.status = 'succeeded'
            if str(item.pk) not in organizable_item_ids:
                item.selected_group_ids = []
            if item.selected_group_ids and item.groups:
                apply_existing_groups(user, item, item.selected_group_ids)
        else:
            item.status = 'pending'
    RssImportItem.objects.bulk_update(items, ['selected_group_ids', 'status', 'outcome'])
    batch.confirmed_request_hash, batch.status = digest, 'confirmed'
    batch.options = {**batch.options, 'selected_ids': selected, 'group_map': resolved}
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
    document = ET.Element('opml', version='2.0')
    ET.SubElement(ET.SubElement(document, 'head'), 'title').text = '我的订阅'
    body = ET.SubElement(document, 'body')
    root_outlines = {}
    child_outlines = {}
    subscriptions = ChannelSubscription.objects.filter(user=user).select_related(
        'source__publication',
    ).prefetch_related('groups__root', 'source__feed_links__binding')
    for subscription in subscriptions:
        groups = list(subscription.groups.all())
        destinations = groups or [None]
        urls = [
            link.binding.rsshub_alias or link.binding.canonical_feed_url
            for link in subscription.source.feed_links.all()
        ]
        if not urls:
            from api.services.source_policy import policy_for_name
            policy = policy_for_name(subscription.source.name)
            if policy and policy.feed_url:
                urls.append(policy.feed_url)
        for feed_url in dict.fromkeys(urls):
            try:
                if feed_url.startswith('rsshub://'):
                    from api.rss.rsshub_url import normalize_alias
                    url = normalize_alias(feed_url)
                else:
                    url = canonicalize_feed_url(feed_url, resolve_rsshub=False)
            except ValueError:
                continue
            for group in destinations:
                parent = body
                if group is not None:
                    if group.root_id not in root_outlines:
                        root_outlines[group.root_id] = ET.SubElement(
                            body, 'outline', text=group.root.name, title=group.root.name,
                        )
                    if group.pk not in child_outlines:
                        child_outlines[group.pk] = ET.SubElement(
                            root_outlines[group.root_id], 'outline',
                            text=group.name, title=group.name,
                        )
                    parent = child_outlines[group.pk]
                name = subscription.source.publication.display_name or subscription.source.name
                ET.SubElement(parent, 'outline', type='rss', text=name, title=name, xmlUrl=url)
    return ET.tostring(document, encoding='utf-8', xml_declaration=True)
