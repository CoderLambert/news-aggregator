"""Personal subscriptions over shared physical feeds. No network in transactions."""
from hashlib import sha256
import json
import os
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.http import Http404
from rest_framework.exceptions import APIException, Throttled, ValidationError

from api.models import Category, ChannelGroup, ChannelGroupMember, ChannelSubscription, Source
from api.rss.directory_models import FeedDirectoryEntry
from api.rss.discovery import resolve_candidate_token
from api.rss.http import RssConflict
from api.rss.feed_policy import approved_feed_policy, assert_binding_policy
from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
from api.rss.operations import (canonicalize_feed_url, cancel_operation, enqueue_operation,
                                get_or_create_binding, reconcile_binding, sqlite_retry)


class EngineUnavailable(APIException):
    status_code = 503
    default_detail = 'RSS 引擎尚未配置。'
    default_code = 'engine_unavailable'


def engine_identity():
    # The web app needs identity only, never the engine admin/collector secret.
    try:
        instance = UUID(os.environ['RSS_ENGINE_INSTANCE_UUID'])
        account = int(os.environ['RSS_ENGINE_ACCOUNT_ID'])
        if not 0 < account < 2**63:
            raise ValueError
        return instance, account
    except (KeyError, ValueError):
        raise EngineUnavailable from None


def _selection(user, data):
    selectors = [name for name in ('feed_url', 'candidate_token', 'directory_entry_id') if name in data]
    if len(selectors) != 1 or set(data) - {*selectors, 'group_ids', 'category_id'}:
        raise ValidationError('请选择一种订阅方式。')
    name = ''
    if selectors[0] == 'candidate_token':
        url = resolve_candidate_token(user, data['candidate_token'])
    elif selectors[0] == 'directory_entry_id':
        try:
            identity = UUID(str(data['directory_entry_id']))
            entry = FeedDirectoryEntry.objects.get(entry_id=identity, snapshot__active=True, visibility='public')
        except (ValueError, FeedDirectoryEntry.DoesNotExist):
            raise Http404 from None
        if entry.kind != 'feed' or entry.required_parameters or entry.capability_requirements:
            raise ValidationError('此路线需要额外配置，暂不能直接订阅。')
        url, name = entry.public_url, entry.name
    else:
        url = data['feed_url']
    return canonicalize_feed_url(url), name


def _group_ids(value):
    if not isinstance(value, list) or len(value) > 100 or any(type(x) is not int or x <= 0 for x in value):
        raise ValidationError('group_ids 须为最多100个分组ID。')
    return sorted(set(value))


def subscription_data(subscription):
    publication = subscription.source.publication
    links = list(subscription.source.feed_links.select_related('binding').order_by('pk'))
    return {'id': subscription.pk, 'source_id': subscription.source_id,
            'name': publication.display_name or subscription.source.name,
            'group_ids': sorted(subscription.groups.values_list('pk', flat=True)),
            'category_id':subscription.category_id,'category_version':subscription.category_version,
            'publication': publication.publication, 'owner': publication.owner,
            'feeds': [{'id': str(link.binding_id), 'feed_url': link.binding.canonical_feed_url,
                       'connection_state': link.binding.connection_state,
                       'desired_mode': link.binding.desired_mode} for link in links]}


def _subscription_result(user, operation):
    identity = operation.safe_input.get('subscription', {}).get('id')
    subscription = ChannelSubscription.objects.filter(pk=identity, user=user).select_related('source__publication').first()
    return {'subscription': subscription_data(subscription) if subscription else None,
            'operation_id': str(operation.pk), 'state': operation.state,
            'source_id': operation.safe_input.get('subscription_request', operation.safe_input.get('subscription', {})).get('source_id')}


@sqlite_retry
@transaction.atomic
def subscribe(user, data, idempotency_key):
    if not isinstance(data, dict):
        raise ValidationError('请求内容须为对象。')
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128 or not idempotency_key.isprintable():
        raise ValidationError('请提供1–128字符的 Idempotency-Key。')
    # All database reads that drive relation changes follow a SQLite write lock.
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    url, display_name = _selection(user, data)
    group_ids = _group_ids(data.get('group_ids', []))
    category_id=data.get('category_id')
    if 'category_id' in data and category_id is not None and (type(category_id) is not int or not Category.objects.filter(pk=category_id).exists()):
        raise ValidationError('请选择有效的频道分类。')
    digest_input={'url':url,'group_ids':group_ids}
    if 'category_id' in data: digest_input['category_id']=category_id
    request_hash = sha256(json.dumps(digest_input, sort_keys=True).encode()).hexdigest()
    key = 'subscribe:' + sha256(idempotency_key.encode()).hexdigest()
    old = FeedOperation.objects.filter(actor=user, dedupe_key=key).first()
    if old:
        if old.request_hash != request_hash or not ({'subscription', 'subscription_request'} & old.safe_input.keys()):
            raise RssConflict('幂等键已用于不同的请求。', code='idempotency_conflict')
        return 200, _subscription_result(user, old)
    from api.rss.additions import check_addition_limit
    check_addition_limit(user, url)
    admission = approved_feed_policy(url)
    groups = list(ChannelGroup.objects.filter(user=user, pk__in=group_ids))
    if len(groups) != len(group_ids):
        raise Http404
    instance, account = engine_identity()
    binding = FeedBinding.objects.filter(engine_instance_uuid=instance, account_id=account,
                                         canonical_feed_url=url).first()
    if binding is None:
        binding = get_or_create_binding(instance, account, url,
            desired_mode=admission.desired_mode)
    assert_binding_policy(binding)
    if binding.source_links.filter(source__publication__owner='legacy').exists():
        raise RssConflict('此来源正在迁移，请稍后订阅。', code='source_migration_required')
    link = binding.source_links.filter(association_policy={'version': 1, 'mode': 'all'}).select_related('source__publication').order_by('source__publication__requires_public_membership', 'pk').first()
    if link is None:
        parsed = urlsplit(url)
        name = display_name or parsed.hostname
        if binding.rsshub_alias and not display_name:
            from api.rss.rsshub_url import metadata
            template,_,params=metadata(binding.rsshub_alias)
            name=('Twitter @'+params['id']) if template=='twitter.user' else binding.rsshub_alias
        source = Source.objects.create(name=f'{name[:60]} · {binding.pk}',
            url=f'https://{parsed.netloc}', country='', language='')
        SourcePublication.objects.create(source=source, publication='personal', owner='miniflux',
                                         reading_policy=admission.reading_policy, display_name=name[:255])
        link = SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
    else:
        source = link.source
        if not hasattr(source, 'publication'):
            raise RssConflict('来源配置尚未完成。')
        if not link.enabled and source.publication.owner == 'miniflux':
            link.enabled = True
            link.save(update_fields=['enabled'])
    pending_sources = FeedOperation.objects.filter(actor=user, safe_input__subscription_request__isnull=False,
        state__in=['pending', 'running', 'retry_wait', 'unknown', 'manual_blocked']).values_list(
            'safe_input__subscription_request__source_id', flat=True)
    if (not ChannelSubscription.objects.filter(user=user, source=source).exists()
            and source.pk not in pending_sources
            and ChannelSubscription.objects.filter(user=user).count() + len(set(pending_sources)) >= int(getattr(settings, 'RSS_SUBSCRIPTION_LIMIT', 500))):
        raise Throttled(detail='已达到订阅数量上限。')
    operation = enqueue_operation('register' if binding.engine_feed_id is None else 'set_enabled',
        actor=user, dedupe_key=key, binding=binding)
    request_data={'source_id':source.pk,'url':url,'group_ids':group_ids}
    if 'category_id' in data:
        current=ChannelSubscription.objects.filter(user=user,source=source).first()
        request_data.update(category_id=category_id,category_expected_version=current.category_version if current else 0)
    FeedOperation.objects.filter(pk=operation.pk).update(request_hash=request_hash,
        safe_input={'subscription_request':request_data})
    # The durable request holds a collection reference, but grants no article ACL.
    reconcile_binding(binding.pk)
    binding.refresh_from_db()
    FeedOperation.objects.filter(pk=operation.pk).update(intent_version=binding.policy_version)
    operation.refresh_from_db()
    from api.rss.operations import unresolved_control_operations
    ready = (not unresolved_control_operations(binding.pk).exists() and binding.engine_feed_id is not None and binding.connection_state in {'ready', 'paused'}
             and binding.applied_policy_version == binding.policy_version)
    if ready:
        complete_subscription(operation)
        operation.refresh_from_db()
    return (201 if ready else 202), _subscription_result(user, operation)


def complete_subscription(operation):
    """Called only under the worker's current lease/policy transaction or a ready binding.

    Unknown/failed/cancelled results never grant a relationship. Replays after
    unsubscribe cannot recreate it because subscription_request is consumed.
    """
    request = operation.safe_input.get('subscription_request')
    if not request or operation.actor_id is None or not operation.actor.is_active:
        return
    group_ids = request['group_ids']
    groups = list(ChannelGroup.objects.filter(user_id=operation.actor_id, pk__in=group_ids))
    if len(groups) != len(group_ids):
        return
    subscription, _ = ChannelSubscription.objects.get_or_create(user_id=operation.actor_id, source_id=request['source_id'])
    if 'category_id' in request:
        newer=FeedOperation.objects.filter(actor_id=operation.actor_id,binding_id=operation.binding_id,
            created_at__gt=operation.created_at,safe_input__subscription_request__category_id__isnull=False).exclude(state__in=['cancelled','failed']).exists()
        if not newer and (request['category_id'] is None or Category.objects.filter(pk=request['category_id']).exists()):
            ChannelSubscription.objects.filter(pk=subscription.pk,category_version=request.get('category_expected_version',0)).update(
                category_id=request['category_id'],category_version=F('category_version')+1)
    ChannelGroupMember.objects.bulk_create([ChannelGroupMember(group=g, subscription=subscription) for g in groups], ignore_conflicts=True)
    FeedOperation.objects.filter(pk=operation.pk).update(safe_input={
        'subscription': {**request, 'id': subscription.pk}})
    from api.rss.import_models import RssImportItem
    RssImportItem.objects.filter(operation=operation).update(subscription=subscription, status='succeeded')



@sqlite_retry
@transaction.atomic
def unsubscribe(user, subscription_id):
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    subscription = ChannelSubscription.objects.filter(pk=subscription_id).first()
    if subscription is None:
        return
    if subscription.user_id != user.pk:
        raise Http404
    source_id = subscription.source_id
    bindings = list(SourceFeedLink.objects.filter(source_id=source_id).values_list('binding_id', flat=True))
    subscription.delete()  # Through-group rows only; article/user history remains.
    for operation in FeedOperation.objects.filter(actor=user, binding_id__in=bindings,
            safe_input__subscription__id=subscription_id):
        cancel_operation(user, operation.pk)
    for binding_id in bindings:
        reconcile_binding(binding_id)
