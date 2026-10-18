"""Preview/apply separation and additive, owner-scoped channel organization."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError
from api.models import ChannelGroup, ChannelGroupMember, ChannelSubscription, Source
from api.smart_channel_models import ChannelGroupingConfig, ChannelGroupingOverride, ChannelGroupingProposal, SubscriptionGroupingState
from api.ai_connection_models import UserAIConnection
from api.services.channel_topics import TOPIC_MAP, digest, evidence_for, profile_data
from api.services.channel_topic_hints import infer_title_topics


class GroupingConflict(APIException):
    status_code = 409
    default_detail = '订阅、分组或来源资料已变更，请重新生成预览。'


def lock_user(user):
    if not user.is_active:
        raise PermissionDenied('账号不可用。')
    User.objects.filter(pk=user.pk).update(last_login=F('last_login'))
    User.objects.select_for_update().get(pk=user.pk)


def config_data(user):
    cfg = ChannelGroupingConfig.objects.filter(user=user).first()
    owned = set(ChannelGroup.objects.filter(user=user).values_list('id', flat=True))
    return {'mode': cfg.mode if cfg else 'suggest',
            'bindings': {k: v for k, v in (cfg.bindings if cfg else {}).items() if k in TOPIC_MAP and v in owned},
            'revision': cfg.revision if cfg else 0}


def credential_fingerprint(user):
    active = list(UserAIConnection.objects.filter(
        user=user, is_deleted=False, is_enabled=True
    ).order_by('id').values_list('id', 'credential_epoch'))
    return digest([[str(identity), epoch] for identity, epoch in active]) if active else ''


def snapshot(user, source_ids):
    subscriptions = list(ChannelSubscription.objects.filter(user=user).order_by('id').values_list('id', 'source_id', 'created_at'))
    groups = []
    for group in ChannelGroup.objects.filter(user=user).prefetch_related('subscriptions').order_by('id'):
        groups.append([group.id, group.name, sorted(group.subscriptions.values_list('source_id', flat=True))])
    profiles = [profile_data(source)['evidence_hash'] for source in Source.objects.filter(pk__in=source_ids).order_by('id')]
    overrides = list(ChannelGroupingOverride.objects.filter(user=user).order_by('id').values_list('source_id', 'group_id', 'suppressed', 'touched_at'))
    return digest([subscriptions, groups, profiles, config_data(user), overrides])


def validated_ids(value, limit=200):
    if not isinstance(value, list) or len(value) > limit or any(type(x) is not int or x <= 0 for x in value):
        raise ValidationError('频道 ID 必须为正整数数组，且不能超过本次处理上限。')
    return sorted(set(value))


def validated_topics(value):
    if not isinstance(value, list) or not 1 <= len(value) <= len(TOPIC_MAP) or any(not isinstance(x, str) or x not in TOPIC_MAP for x in value):
        raise ValidationError('请选择有效的主题预设。')
    return sorted(set(value))


def validated_mode(value):
    if value not in ('off', 'suggest', 'auto'):
        raise ValidationError('无效的自动整理模式。')
    return value


def proposal_data(proposal):
    return {'id': str(proposal.id), 'engine': proposal.engine, 'status': proposal.status,
            'source_ids': proposal.source_ids, 'topic_keys': proposal.topic_keys,
            'result': proposal.result, 'error_code': proposal.error_code,
            'created_at': proposal.created_at.isoformat(), 'expires_at': proposal.expires_at.isoformat(),
            'applied_count': len(proposal.applied_changes), 'model_id': proposal.model_id,
            'attempts': proposal.attempts}


@transaction.atomic
def make_proposal(user, payload):
    lock_user(user)
    engine = payload.get('engine', 'rules')
    if engine not in ('rules', 'ai'):
        raise ValidationError('无效的分类引擎。')
    source_ids = validated_ids(payload.get('source_ids', list(ChannelSubscription.objects.filter(user=user).values_list('source_id', flat=True))), 40 if engine == 'ai' else 200)
    if not source_ids:
        raise ValidationError('请先订阅至少一个频道。')
    topic_keys = validated_topics(payload.get('topic_keys', list(TOPIC_MAP)))
    if ChannelSubscription.objects.filter(user=user, source_id__in=source_ids).count() != len(source_ids):
        raise NotFound('只能整理自己的已订阅频道。')
    try:
        request_id = uuid.UUID(str(payload.get('request_id', uuid.uuid4())))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('无效的请求标识。') from None
    request_hash = digest([engine, source_ids, topic_keys])
    previous = ChannelGroupingProposal.objects.filter(user=user, request_id=request_id).first()
    if previous:
        if previous.request_hash != request_hash:
            raise GroupingConflict('同一请求标识不能用于不同的操作。')
        return previous
    now = timezone.now()
    recent = ChannelGroupingProposal.objects.filter(user=user, created_at__gte=now - timedelta(hours=1))
    if recent.count() >= 30:
        raise Throttled(3600, '整理请求过多，请稍后再试。')
    fingerprint = ''
    if engine == 'ai':
        if not settings.PUBLIC_AI_ENABLED:
            raise PermissionDenied('站点 AI 功能已关闭。')
        if payload.get('consent') is not True:
            raise ValidationError('需要明确同意使用本人模型额度。')
        fingerprint = credential_fingerprint(user)
        if not fingerprint:
            raise ValidationError('请先在设置中配置自己的模型 API Key。')
        if ChannelGroupingProposal.objects.filter(user=user, engine='ai', created_at__date=timezone.localdate()).count() >= 20:
            raise Throttled(3600, '已达到今日 AI 整理任务上限。')
    sources = list(Source.objects.filter(id__in=source_ids).order_by('id'))
    evidence = [evidence_for(source) for source in sources]
    result = []
    for source, source_evidence in zip(sources, evidence, strict=True):
        profile = profile_data(source)
        topics = [key for key in profile['topics'] if key in topic_keys]
        origin, needs_review = profile['origin'], profile['needs_review']
        reason = '根据已登记频道的主题资料' if topics else '资料不足，保留待确认'
        # Only an explicit, user-triggered *rules* preview receives weak hints.
        # A manually emptied profile is authoritative; AI and the public
        # catalog/auto-subscribe paths must not turn these into trusted topics.
        if engine == 'rules' and not topics and origin == 'unknown':
            hints = [hint for hint in infer_title_topics(source_evidence['titles'])
                     if hint['topic_key'] in topic_keys]
            if hints:
                topics = [hint['topic_key'] for hint in hints]
                origin, needs_review = 'title_evidence', True
                matches = '、'.join(f"{TOPIC_MAP[hint['topic_key']]['name']} {hint['matched_titles']} 篇" for hint in hints)
                reason = f"最近 {hints[0]['total_titles']} 篇不同文章标题：{matches}；仅供人工确认。"
        result.append({'source_id': source.id, 'name': source.name, 'topic_keys': topics,
                       'origin': origin, 'needs_review': needs_review, 'reason': reason})
    return ChannelGroupingProposal.objects.create(user=user, request_id=request_id, engine=engine,
        status='queued' if engine == 'ai' else 'ready', source_ids=source_ids, topic_keys=topic_keys,
        input_snapshot=snapshot(user, source_ids), request_hash=request_hash, evidence=evidence,
        credential_fingerprint=fingerprint, result=result, expires_at=now + timedelta(hours=24))


@transaction.atomic
def apply_proposal(user, proposal_id, payload):
    lock_user(user)
    proposal = ChannelGroupingProposal.objects.filter(pk=proposal_id, user=user, public_source__isnull=True).first()
    if not proposal:
        raise NotFound()
    if proposal.status == 'applied':
        return proposal
    if proposal.status != 'ready' or proposal.expires_at <= timezone.now():
        raise GroupingConflict('预览尚未就绪、已取消或已过期，请重新整理。')
    if proposal.input_snapshot != snapshot(user, proposal.source_ids):
        raise GroupingConflict()
    if proposal.engine == 'ai' or any(item.get('origin') == 'title_evidence' for item in proposal.result):
        from api.services.classification_evidence import evidence_is_current
        if not evidence_is_current(proposal):
            raise GroupingConflict('频道标题证据或资料已变化，请重新生成预览；不会自动调用模型。')
    entries = payload.get('groups')
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(TOPIC_MAP):
        raise ValidationError('请选择要应用的分组。')
    cfg, _ = ChannelGroupingConfig.objects.get_or_create(user=user)
    mode = validated_mode(payload.get('mode', cfg.mode))
    seen_topics, created_names, changes = set(), {}, []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError('无效的分组变更。')
        key = entry.get('topic_key')
        if key not in proposal.topic_keys or key in seen_topics:
            raise ValidationError('主题必须来自本次预览且不可重复。')
        seen_topics.add(key)
        source_ids = validated_ids(entry.get('source_ids', []))
        if any(source_id not in proposal.source_ids for source_id in source_ids):
            raise NotFound()
        if not source_ids:
            continue
        group_id = entry.get('group_id')
        if group_id is not None:
            if type(group_id) is not int:
                raise ValidationError('无效的分组 ID。')
            group = ChannelGroup.objects.filter(pk=group_id, user=user).first()
            if not group:
                raise NotFound()
        else:
            name = entry.get('name', TOPIC_MAP[key]['name'])
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                raise ValidationError('分组名称应为 1–40 字。')
            name = name.strip()
            group = created_names.get(name)
            if group is None:
                if ChannelGroup.objects.filter(user=user, name=name).exists():
                    raise GroupingConflict('已有同名分组，请显式选择该分组或使用不同名称。')
                group = ChannelGroup.objects.create(user=user, name=name)
                created_names[name] = group
        cfg.bindings[key] = group.pk
        for subscription in ChannelSubscription.objects.filter(user=user, source_id__in=source_ids):
            if ChannelGroupingOverride.objects.filter(user=user, source_id=subscription.source_id, group=group, suppressed=True).exists():
                continue
            member, created = ChannelGroupMember.objects.get_or_create(group=group, subscription=subscription)
            if created:
                changes.append({'member_id': member.pk, 'source_id': subscription.source_id, 'group_id': group.pk})
    cfg.mode = mode
    cfg.revision += 1
    cfg.active_since = timezone.now()
    cfg.save()
    proposal.status = 'applied'
    proposal.applied_at = timezone.now()
    proposal.applied_changes = changes
    proposal.save(update_fields=['status', 'applied_at', 'applied_changes'])
    return proposal


@transaction.atomic
def undo_proposal(user, proposal_id):
    lock_user(user)
    proposal = ChannelGroupingProposal.objects.filter(pk=proposal_id, user=user, public_source__isnull=True).first()
    if not proposal:
        raise NotFound()
    if proposal.status == 'undone':
        return proposal
    if proposal.status != 'applied':
        raise GroupingConflict('只有已应用的整理可以撤销。')
    for change in proposal.applied_changes:
        touched = ChannelGroupingOverride.objects.filter(user=user, source_id=change['source_id'], group_id=change['group_id'], touched_at__gt=proposal.applied_at).exists()
        if touched:
            continue
        deleted, _ = ChannelGroupMember.objects.filter(pk=change['member_id'], group__user=user,
            group_id=change['group_id'], subscription__user=user, subscription__source_id=change['source_id']).delete()
        if deleted:
            ChannelGroupingOverride.objects.update_or_create(user=user, source_id=change['source_id'], group_id=change['group_id'], defaults={'suppressed': True})
    proposal.status = 'undone'
    proposal.save(update_fields=['status'])
    return proposal


def mark_manual(user, source_id, before, after):
    for group_id in set(before) | set(after):
        if ChannelGroup.objects.filter(pk=group_id, user=user).exists():
            ChannelGroupingOverride.objects.update_or_create(user=user, source_id=source_id, group_id=group_id,
                defaults={'suppressed': group_id not in after})


@transaction.atomic
def process_subscription(subscription_id):
    subscription = ChannelSubscription.objects.select_related('user', 'source').filter(pk=subscription_id).first()
    if not subscription or not subscription.user.is_active:
        return
    user = subscription.user
    lock_user(user)
    cfg = ChannelGroupingConfig.objects.filter(user=user).first()
    if not cfg or cfg.mode == 'off' or not cfg.bindings or subscription.created_at < cfg.active_since:
        return
    profile = profile_data(subscription.source)
    state, _ = SubscriptionGroupingState.objects.get_or_create(subscription=subscription)
    signature = digest([profile['evidence_hash'], profile['topics'], profile['origin'], cfg.revision])
    if state.profile_hash == signature:
        return
    state.profile_hash = signature
    topic_keys = [key for key in profile['topics'] if key in cfg.bindings and
        ChannelGroup.objects.filter(pk=cfg.bindings[key], user=user).exists()]
    if not topic_keys:
        state.status = 'pending'
        state.save()
        return
    if cfg.mode == 'auto' and not profile['needs_review'] and profile['origin'] in {'policy', 'catalog', 'manual'}:
        changes = []
        for key in topic_keys:
            group_id = cfg.bindings[key]
            if ChannelGroupingOverride.objects.filter(user=user, source=subscription.source, group_id=group_id, suppressed=True).exists():
                continue
            member, created = ChannelGroupMember.objects.get_or_create(group_id=group_id, subscription=subscription)
            if created:
                changes.append({'member_id': member.pk, 'source_id': subscription.source_id, 'group_id': group_id})
        if changes:
            ChannelGroupingProposal.objects.create(user=user, engine='rules', status='applied', source_ids=[subscription.source_id],
                topic_keys=topic_keys, input_snapshot='', applied_at=timezone.now(), applied_changes=changes,
                result=[{'source_id': subscription.source_id, 'name': subscription.source.name, 'topic_keys': topic_keys,
                         'origin': profile['origin'], 'reason': '根据已开启的自动归组设置', 'needs_review': False}],
                expires_at=timezone.now() + timedelta(days=1))
        state.status = 'applied'
    else:
        make_proposal(user, {'source_ids': [subscription.source_id], 'topic_keys': topic_keys, 'engine': 'rules'})
        state.status = 'suggested'
    state.save()
