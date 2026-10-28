"""Preview/apply separation and additive, owner-scoped channel organization."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError
from api.models import ChannelGroup, ChannelGroupMember, ChannelGroupRoot, ChannelSubscription, Source
from api.smart_channel_models import ChannelGroupingConfig, ChannelGroupingOverride, ChannelGroupingProposal, SubscriptionGroupingState
from api.ai_connection_models import UserAIConnection
from api.services.channel_topics import TOPIC_MAP, digest, evidence_for, profile_data
from api.services.channel_topic_hints import infer_title_topics


class GroupLimitExceeded(ValidationError):
    default_detail = '本次最多整理 200 个个人分组。'
    default_code = 'group_limit_exceeded'


class GroupingConflict(APIException):
    status_code = 409
    default_detail = '订阅、分组或来源资料已变更，请重新生成预览。'


def lock_user(user):
    if not user.is_active:
        raise PermissionDenied('账号不可用。')
    User.objects.filter(pk=user.pk).update(last_login=F('last_login'))
    User.objects.select_for_update().get(pk=user.pk)


def record_group_structure_change(user, *, root_ids=(), removed_group_ids=(), exclude_proposal_id=None):
    """Fence stale grouping work after one already-validated structural mutation."""
    now = timezone.now()
    root_ids = {identity for identity in root_ids if identity is not None}
    if root_ids:
        ChannelGroupRoot.objects.filter(user=user, pk__in=root_ids).update(
            version=F('version') + 1, updated_at=now,
        )
    cfg, _ = ChannelGroupingConfig.objects.get_or_create(user=user)
    removed_group_ids = set(removed_group_ids)
    if removed_group_ids:
        cfg.bindings = {
            key: group_id for key, group_id in cfg.bindings.items()
            if group_id not in removed_group_ids
        }
    cfg.revision += 1
    cfg.scan_cursor = 0
    cfg.save(update_fields=['bindings', 'revision', 'scan_cursor', 'updated_at'])
    stale = ChannelGroupingProposal.objects.filter(
        user=user, background=True, target__in=['groups', 'hierarchy'],
        status__in=['queued', 'running', 'ready'],
    )
    if exclude_proposal_id is not None:
        stale = stale.exclude(pk=exclude_proposal_id)
    stale.update(
        status='cancelled', error_code='configuration_changed',
        lease_token='', lease_until=None,
    )


def config_data(user):
    cfg = ChannelGroupingConfig.objects.filter(user=user).first()
    owned = set(ChannelGroup.objects.filter(user=user).values_list('id', flat=True))
    return {'mode': cfg.mode if cfg else 'suggest',
            'bindings': {k: v for k, v in (cfg.bindings if cfg else {}).items() if k in TOPIC_MAP and v in owned},
            'revision': cfg.revision if cfg else 0,
            'match_existing': cfg.match_existing if cfg else False,
            'ai_enabled': cfg.ai_enabled if cfg else False,
            'ai_model_id': cfg.ai_model_id if cfg else None,
            'daily_limit': cfg.daily_limit if cfg else 10}


def credential_fingerprint(user):
    active = list(UserAIConnection.objects.filter(
        user=user, is_deleted=False, is_enabled=True
    ).order_by('id').values_list('id', 'credential_epoch'))
    return digest([[str(identity), epoch] for identity, epoch in active]) if active else ''


def hierarchy_state(user):
    roots = list(ChannelGroupRoot.objects.filter(user=user).order_by('id')[:21])
    if len(roots) > 20:
        raise GroupLimitExceeded('一次层级整理最多覆盖 20 个根分类。')
    groups = list(ChannelGroup.objects.filter(user=user).prefetch_related('subscriptions').order_by('id')[:201])
    if not groups:
        raise ValidationError('请先创建至少一个子分组。')
    if len(groups) > 200:
        raise GroupLimitExceeded()
    root_ids = {root.pk for root in roots}
    if any(group.root_id is not None and group.root_id not in root_ids for group in groups):
        raise GroupingConflict('分组层级不完整，请刷新后重试。')
    children = [{
        'group_id': group.pk,
        'root_id': group.root_id,
        'name': group.name,
        'version': group.version,
        'source_ids': sorted(subscription.source_id for subscription in group.subscriptions.all()),
    } for group in groups]
    selected_source_ids = []
    for child in children:
        for source_id in child['source_ids']:
            if source_id not in selected_source_ids:
                selected_source_ids.append(source_id)
                if len(selected_source_ids) == 40:
                    break
        if len(selected_source_ids) == 40:
            break
    evidence_hashes = [
        [source.pk, profile_data(source)['evidence_hash']]
        for source in Source.objects.filter(pk__in=selected_source_ids).order_by('id')
    ]
    overrides = list(ChannelGroupingOverride.objects.filter(
        user=user, source_id__in=selected_source_ids,
    ).order_by('id').values_list('source_id', 'group_id', 'suppressed', 'touched_at'))
    return {
        'schema_version': 2,
        'roots': [{
            'root_id': root.pk, 'name': root.name, 'version': root.version,
        } for root in roots],
        'children': children,
        'selected_source_ids': selected_source_ids,
        'evidence_hashes': evidence_hashes,
        'config': config_data(user),
        'overrides': overrides,
    }


def snapshot(user, source_ids, target='topics'):
    if target == 'hierarchy':
        return digest(hierarchy_state(user))
    subscriptions_query = ChannelSubscription.objects.filter(user=user)
    if target == 'groups':
        subscriptions_query = subscriptions_query.filter(source_id__in=source_ids)
    subscriptions = list(subscriptions_query.order_by('id').values_list('id', 'source_id', 'created_at'))
    groups = []
    for group in ChannelGroup.objects.filter(user=user).prefetch_related('subscriptions').order_by('id'):
        groups.append([group.id, group.name, sorted(s.source_id for s in group.subscriptions.all())])
    profiles = [profile_data(source)['evidence_hash'] for source in Source.objects.filter(pk__in=source_ids).order_by('id')]
    overrides = list(ChannelGroupingOverride.objects.filter(user=user).order_by('id').values_list('source_id', 'group_id', 'suppressed', 'touched_at'))
    config = config_data(user)
    if target == 'topics':
        # Preserve pre-upgrade legacy preview fingerprints.
        config = {key: config[key] for key in ('mode', 'bindings', 'revision')}
    return digest([subscriptions, groups, profiles, config, overrides])


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
    skipped = sum(
        change.get('undo_status') == 'skipped' for change in proposal.applied_changes
        if isinstance(change, dict)
    )
    return {'id': str(proposal.id), 'engine': proposal.engine, 'status': proposal.status, 'target': proposal.target,
            'source_ids': proposal.source_ids, 'topic_keys': proposal.topic_keys,
            'result': proposal.result, 'error_code': proposal.error_code,
            'created_at': proposal.created_at.isoformat(), 'expires_at': proposal.expires_at.isoformat(),
            'applied_count': len(proposal.applied_changes), 'undo_skipped': skipped,
            'model_id': proposal.model_id, 'attempts': proposal.attempts}


@transaction.atomic
def make_proposal(user, payload, *, background=False):
    lock_user(user)
    engine = payload.get('engine', 'rules')
    if engine not in ('rules', 'ai'):
        raise ValidationError('无效的分类引擎。')
    target = payload.get('target', 'topics')
    if target not in ('topics', 'groups', 'hierarchy'):
        raise ValidationError('无效的整理目标。')
    if target == 'hierarchy' and (engine != 'ai' or background):
        raise ValidationError('层级整理只能由本人明确发起 AI 预览。')

    group_snapshot = hierarchy_state(user) if target == 'hierarchy' else (
        private_groups(user) if target == 'groups' else []
    )
    if target == 'hierarchy':
        source_ids = group_snapshot['selected_source_ids']
    else:
        if target == 'groups' and 'source_ids' not in payload:
            raise ValidationError('请明确选择自己的订阅。')
        source_ids = validated_ids(
            payload.get('source_ids', list(ChannelSubscription.objects.filter(
                user=user,
            ).values_list('source_id', flat=True))),
            40 if engine == 'ai' else 200,
        )
        if not source_ids:
            raise ValidationError('请先订阅至少一个频道。')
        if target == 'groups' and len(source_ids) != len(payload['source_ids']):
            raise ValidationError('频道 ID 不可重复。')
    topic_keys = validated_topics(
        payload.get('topic_keys', list(TOPIC_MAP)),
    ) if target == 'topics' else []
    if target == 'groups' and not group_snapshot['children'] and engine == 'rules':
        raise ValidationError('请先创建个人分组，或使用 AI 自动规划新分组。')
    if source_ids and ChannelSubscription.objects.filter(
        user=user, source_id__in=source_ids,
    ).count() != len(source_ids):
        raise NotFound('只能整理自己的已订阅频道。')
    try:
        request_id = uuid.UUID(str(payload.get('request_id', uuid.uuid4())))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('无效的请求标识。') from None
    request_parts = [engine, source_ids, topic_keys]
    if target != 'topics':
        request_parts.append(target)
    if engine == 'ai' and payload.get('model_config_id') is not None:
        request_parts.append(payload['model_config_id'])
    request_hash = digest(request_parts)
    previous = ChannelGroupingProposal.objects.filter(user=user, request_id=request_id).first()
    if previous:
        if previous.request_hash != request_hash:
            raise GroupingConflict('同一请求标识不能用于不同的操作。')
        return previous
    if target == 'hierarchy' and ChannelGroupingProposal.objects.filter(
        user=user, target='hierarchy', status__in=['queued', 'running', 'ready'],
    ).exists():
        raise GroupingConflict('已有待处理的层级整理，请先完成或取消。')
    now = timezone.now()
    recent = ChannelGroupingProposal.objects.filter(user=user, created_at__gte=now - timedelta(hours=1))
    if recent.count() >= 30:
        raise Throttled(3600, '整理请求过多，请稍后再试。')
    fingerprint = ''
    execution_snapshot = {}
    if engine == 'ai':
        if not settings.PUBLIC_AI_ENABLED:
            raise PermissionDenied('站点 AI 功能已关闭。')
        if not background and payload.get('consent') is not True:
            raise ValidationError('需要明确同意使用本人模型额度。')
        fingerprint = credential_fingerprint(user)
        if not fingerprint:
            raise ValidationError('请先在设置中配置自己的模型 API Key。')
        from api.services.channel_model import capture_model, ClassificationAuthorizationChanged
        try:
            if background:
                from api.services.channel_model import verify_model
                cfg = ChannelGroupingConfig.objects.get(user=user)
                if not cfg.ai_enabled or cfg.mode == 'off':
                    raise ClassificationAuthorizationChanged()
                execution_snapshot = cfg.execution_snapshot
                verify_model(execution_snapshot, owner_id=user.pk, scope='personal')
            else:
                execution_snapshot = capture_model(
                    user, scope='personal', model_config_id=payload.get('model_config_id'),
                )
        except ClassificationAuthorizationChanged:
            raise ValidationError('请先配置并验证个人默认模型，再明确同意本次分类。') from None
        daily_limit = cfg.daily_limit if background else 20
        if ChannelGroupingProposal.objects.filter(
            user=user, engine='ai', public_source__isnull=True,
            created_at__date=timezone.localdate(),
        ).count() >= daily_limit:
            raise Throttled(3600, '已达到今日 AI 整理任务上限。')
    sources = list(Source.objects.filter(id__in=source_ids).order_by('id'))
    evidence = [evidence_for(source) for source in sources]
    result = []
    if target != 'hierarchy':
        for source, source_evidence in zip(sources, evidence, strict=True):
            profile = profile_data(source)
            topics = [key for key in profile['topics'] if key in topic_keys]
            origin, needs_review = profile['origin'], profile['needs_review']
            reason = '根据已登记频道的主题资料' if topics else '资料不足，保留待确认'
            # Only an explicit, user-triggered *rules* preview receives weak hints.
            if engine == 'rules' and not topics and origin == 'unknown':
                hints = [hint for hint in infer_title_topics(source_evidence['titles'])
                         if hint['topic_key'] in topic_keys]
                if hints:
                    topics = [hint['topic_key'] for hint in hints]
                    origin, needs_review = 'title_evidence', True
                    matches = '、'.join(
                        f"{TOPIC_MAP[hint['topic_key']]['name']} {hint['matched_titles']} 篇"
                        for hint in hints
                    )
                    reason = f"最近 {hints[0]['total_titles']} 篇不同文章标题：{matches}；仅供人工确认。"
            result.append({
                'source_id': source.id, 'name': source.name, 'topic_keys': topics,
                'origin': origin, 'needs_review': needs_review, 'reason': reason,
            })
    if target == 'groups':
        result = group_results(user, sources, evidence, group_snapshot)
    input_snapshot = digest(group_snapshot) if target == 'hierarchy' else snapshot(
        user, source_ids, target,
    )
    return ChannelGroupingProposal.objects.create(
        user=user, request_id=request_id, engine=engine, target=target,
        group_snapshot=group_snapshot, background=background,
        status='queued' if engine == 'ai' else 'ready',
        source_ids=source_ids, topic_keys=topic_keys, input_snapshot=input_snapshot,
        request_hash=request_hash, evidence=evidence,
        credential_fingerprint=fingerprint, execution_snapshot=execution_snapshot,
        model_id=execution_snapshot.get('model', {}).get('model_id', ''),
        result=result, expires_at=now + timedelta(hours=24),
    )


def apply_hierarchy(user, proposal, payload):
    if not isinstance(payload, dict) or set(payload) != {'rows'}:
        raise ValidationError('请选择本次层级预览中的建议。')
    rows = payload['rows']
    if not isinstance(rows, list) or not 1 <= len(rows) <= len(proposal.result):
        raise ValidationError('请选择本次层级预览中的建议。')
    allowed = {digest(row): row for row in proposal.result}
    selected = []
    seen_rows = set()
    seen_groups = set()
    for row in rows:
        row_digest = digest(row)
        if row_digest in seen_rows or row_digest not in allowed or row != allowed[row_digest]:
            raise ValidationError('只能应用本次层级预览中的完整建议行。')
        seen_rows.add(row_digest)
        group_ids = row.get('group_ids')
        if any(group_id in seen_groups for group_id in group_ids):
            raise ValidationError('同一子分组不能在本次应用中重复。')
        seen_groups.update(group_ids)
        selected.append(row)

    groups = {
        group.pk: group for group in ChannelGroup.objects.filter(
            user=user, pk__in=seen_groups,
        ).select_related('root')
    }
    if len(groups) != len(seen_groups):
        raise NotFound()
    existing_root_ids = {
        row['root_id'] for row in selected if row['root_id'] is not None
    }
    roots = {
        root.pk: root for root in ChannelGroupRoot.objects.filter(
            user=user, pk__in=existing_root_ids,
        )
    }
    if len(roots) != len(existing_root_ids):
        raise NotFound()
    new_names = {row['root_name'] for row in selected if row['root_name'] is not None}
    if ChannelGroupRoot.objects.filter(user=user).count() + len(new_names) > 40:
        raise ValidationError('每个账号最多创建 40 个根分类。')
    if ChannelGroupRoot.objects.filter(user=user, name__in=new_names).exists():
        raise GroupingConflict('根分类已经变化，请重新生成层级建议。')

    created_roots = {}
    changes = []
    touched_roots = set()
    for row in selected:
        destination = roots.get(row['root_id'])
        if destination is None:
            destination = created_roots.get(row['root_name'])
            if destination is None:
                destination = ChannelGroupRoot.objects.create(
                    user=user, name=row['root_name'],
                )
                created_roots[row['root_name']] = destination
        for group_id in row['group_ids']:
            group = groups[group_id]
            if group.root_id == destination.pk:
                continue
            before_root_id = group.root_id
            before_version = group.version
            group.root = destination
            group.version += 1
            group.save(update_fields=['root', 'version', 'updated_at'])
            touched_roots.update([before_root_id, destination.pk])
            changes.append({
                'child_id': group.pk,
                'before_root_id': before_root_id,
                'before_version': before_version,
                'after_root_id': destination.pk,
                'after_version': group.version,
            })
    record_group_structure_change(
        user, root_ids=touched_roots, exclude_proposal_id=proposal.pk,
    )
    proposal.status = 'applied'
    proposal.applied_at = timezone.now()
    proposal.applied_changes = changes
    proposal.save(update_fields=['status', 'applied_at', 'applied_changes'])
    return proposal


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
    if proposal.input_snapshot != snapshot(user, proposal.source_ids, proposal.target):
        raise GroupingConflict()
    if proposal.target == 'groups' or proposal.engine == 'ai' or any(item.get('origin') == 'title_evidence' for item in proposal.result):
        from api.services.classification_evidence import evidence_is_current
        if not evidence_is_current(proposal):
            raise GroupingConflict('频道标题证据或资料已变化，请重新生成预览；不会自动调用模型。')
    if proposal.target == 'hierarchy':
        return apply_hierarchy(user, proposal, payload)
    if proposal.target == 'groups':
        return apply_group_assignments(user, proposal, payload)
    entries = payload.get('groups')
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(TOPIC_MAP):
        raise ValidationError('请选择要应用的分组。')
    cfg, _ = ChannelGroupingConfig.objects.get_or_create(user=user)
    mode = validated_mode(payload.get('mode', cfg.mode))
    seen_topics, created_names, changes = set(), {}, []
    topic_root = None
    initial_group_count = ChannelGroup.objects.filter(user=user).count()
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
                if initial_group_count + len(created_names) >= 200:
                    raise GroupLimitExceeded()
                if topic_root is None:
                    topic_root = ChannelGroupRoot.objects.filter(user=user, name='主题分组').first()
                    if topic_root is None:
                        if ChannelGroupRoot.objects.filter(user=user).count() >= 40:
                            raise ValidationError('每个账号最多创建 40 个根分类。')
                        topic_root = ChannelGroupRoot.objects.create(user=user, name='主题分组')
                group = ChannelGroup.objects.create(user=user, root=topic_root, name=name)
                created_names[name] = group
        cfg.bindings[key] = group.pk
        for subscription in ChannelSubscription.objects.filter(user=user, source_id__in=source_ids):
            if ChannelGroupingOverride.objects.filter(user=user, source_id=subscription.source_id, group=group, suppressed=True).exists():
                continue
            member, created = ChannelGroupMember.objects.get_or_create(group=group, subscription=subscription)
            if created:
                changes.append({'member_id': member.pk, 'source_id': subscription.source_id, 'group_id': group.pk})
    cfg.mode = mode
    if cfg.mode != 'off' and (cfg.match_existing or cfg.ai_enabled) and cfg.personal_active_since is None:
        cfg.personal_active_since = timezone.now()
    if created_names:
        cfg.save(update_fields=['mode', 'bindings', 'personal_active_since', 'updated_at'])
        record_group_structure_change(
            user, root_ids=[topic_root.pk], exclude_proposal_id=proposal.pk,
        )
    else:
        cfg.revision += 1
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
    if proposal.target == 'hierarchy':
        touched_roots = set()
        changes = []
        for change in proposal.applied_changes:
            group = ChannelGroup.objects.filter(
                pk=change['child_id'], user=user,
                root_id=change['after_root_id'], version=change['after_version'],
            ).first()
            original_root_exists = change['before_root_id'] is None or ChannelGroupRoot.objects.filter(
                pk=change['before_root_id'], user=user,
            ).exists()
            if group is None or not original_root_exists:
                changes.append({**change, 'undo_status': 'skipped'})
                continue
            group.root_id = change['before_root_id']
            group.version += 1
            group.save(update_fields=['root', 'version', 'updated_at'])
            touched_roots.update([change['after_root_id'], change['before_root_id']])
            changes.append({
                **change, 'undo_status': 'restored', 'undo_version': group.version,
            })
        if touched_roots:
            record_group_structure_change(user, root_ids=touched_roots)
        proposal.status = 'undone'
        proposal.applied_changes = changes
        proposal.save(update_fields=['status', 'applied_changes'])
        return proposal
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


def personal_cutoff(cfg, *, anchor=None):
    """First-activation cutoff for personal group organization, None when disabled.

    A config created before this cutoff existed (legacy topics-era row) has no
    personal boundary and must never fall back to the legacy topics
    ``active_since``: that would retroactively organize the existing backlog.
    The first observed personal use anchors the cutoff instead, and the
    conditional update keeps a concurrent save from moving it later.
    """
    if not cfg or cfg.mode == 'off' or not (cfg.match_existing or cfg.ai_enabled):
        return None
    if cfg.personal_active_since is not None:
        return cfg.personal_active_since
    cutoff = timezone.now() if anchor is None else anchor
    updated = ChannelGroupingConfig.objects.filter(pk=cfg.pk, personal_active_since__isnull=True).update(
        personal_active_since=cutoff)
    if not updated:
        cutoff = ChannelGroupingConfig.objects.filter(pk=cfg.pk).values_list('personal_active_since', flat=True).first()
        if cutoff is None:
            return None
    cfg.personal_active_since = cutoff
    return cutoff


@transaction.atomic
def process_subscription(subscription_id, *, group_context=None):
    subscription = ChannelSubscription.objects.select_related('user', 'source').filter(pk=subscription_id).first()
    if not subscription or not subscription.user.is_active:
        return
    user = subscription.user
    try:
        lock_user(user)
    except User.DoesNotExist:
        return
    # The subscription may have been removed while waiting for the owner lock.
    user.refresh_from_db(fields=['is_active'])
    subscription = ChannelSubscription.objects.select_related('source').filter(pk=subscription_id, user=user).first()
    if subscription is None or not user.is_active:
        return
    cfg = ChannelGroupingConfig.objects.filter(user=user).first()
    if not cfg or cfg.mode == 'off':
        return
    if cfg.match_existing or cfg.ai_enabled:
        # Personal organization is bounded only by its own cutoff; the triggering
        # subscription anchors a legacy config and stays eligible, older backlog does not.
        cutoff = personal_cutoff(cfg, anchor=subscription.created_at)
        if cutoff is None or subscription.created_at < cutoff:
            return
        return process_personal_subscription(subscription, cfg, groups=group_context)
    if subscription.created_at < cfg.active_since:
        return
    if not cfg.bindings:
        return
    profile = profile_data(subscription.source)
    state, _ = SubscriptionGroupingState.objects.get_or_create(subscription=subscription)
    signature = digest([profile['evidence_hash'], profile['topics'], profile['origin'], cfg.revision])
    # Applied history and later manual membership changes are authoritative.
    if state.status == 'applied' or state.profile_hash == signature:
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


def private_groups(user):
    """Bounded root/child definitions plus 20 small examples for model context."""
    roots = list(ChannelGroupRoot.objects.filter(user=user).order_by('id')[:41])
    if len(roots) > 40:
        raise GroupLimitExceeded('个人根分类超过 40 个。')
    examples_query = ChannelSubscription.objects.filter(user=user).select_related('source').order_by('id')[:3]
    groups = list(ChannelGroup.objects.filter(user=user).select_related('root').order_by('id').prefetch_related(
        Prefetch('subscriptions', queryset=examples_query, to_attr='organization_examples'))[:201])
    if len(groups) > 200:
        raise GroupLimitExceeded()
    children, evidence_cache, remaining = [], {}, 20
    for group in groups:
        examples = []
        for subscription in group.organization_examples[:remaining]:
            if subscription.source_id not in evidence_cache:
                evidence_cache[subscription.source_id] = evidence_for(subscription.source)
            evidence = evidence_cache[subscription.source_id]
            examples.append({
                'name': evidence['name'][:60], 'about': evidence['about'][:160],
                'titles': [title[:100] for title in evidence['titles'][:2]],
            })
            remaining -= 1
        children.append({
            'group_id': group.pk, 'root_id': group.root_id,
            'root_name': group.root.name if group.root_id else None, 'name': group.name,
            'path': f'{group.root.name} / {group.name}' if group.root_id else group.name, 'examples': examples,
        })
    return {
        'roots': [{'root_id': root.pk, 'name': root.name} for root in roots],
        'children': children,
    }


def group_results(user, sources, evidence, groups):
    cfg = ChannelGroupingConfig.objects.filter(user=user).first()
    children = groups['children']
    by_id = {group['group_id']: group for group in children}
    result = []
    for source, item in zip(sources, evidence, strict=True):
        profile = profile_data(source)
        topics = profile['topics']
        origin, review = profile['origin'], profile['needs_review']
        reason = '根据已审核的频道主题匹配已有子分组'
        if not topics and origin == 'unknown':
            topics = [hint['topic_key'] for hint in infer_title_topics(item['titles'])]
            if topics:
                origin, review = 'title_evidence', True
                reason = '根据已保存文章标题匹配；仅供人工确认。'
        matches = set()
        for topic in topics:
            binding = cfg.bindings.get(topic) if cfg else None
            if binding in by_id:
                matches.add(binding)
                continue
            names = [
                group['group_id'] for group in children
                if group['name'].strip().casefold() in {
                    TOPIC_MAP[topic]['name'].casefold(), topic,
                }
            ]
            if len(names) == 1:
                matches.update(names)
        suppressed = set(ChannelGroupingOverride.objects.filter(
            user=user, source=source, suppressed=True,
        ).values_list('group_id', flat=True))
        matches -= suppressed
        result.append({
            'source_id': source.pk, 'name': source.name, 'topic_keys': [],
            'group_ids': sorted(matches), 'new_group_paths': [],
            'origin': origin, 'needs_review': review or not matches,
            'reason': reason if matches else '资料不足或没有可靠匹配，保留待确认',
        })
    return result


def apply_group_assignments(user, proposal, payload):
    if proposal.group_snapshot != private_groups(user):
        raise GroupingConflict()
    entries = payload.get('assignments') if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(proposal.source_ids):
        raise ValidationError('请选择本次预览的频道和子分组。')
    snapshot_children = proposal.group_snapshot['children']
    allowed_group_ids = {group['group_id'] for group in snapshot_children}
    owned_group_ids = set(ChannelGroup.objects.filter(user=user).values_list('pk', flat=True))
    allowed_paths = {
        digest(path): path
        for item in proposal.result
        for path in item.get('new_group_paths', [])
        if isinstance(path, dict)
    }
    seen_sources = set()
    normalized = []
    requested_paths = {}
    for entry in entries:
        if (not isinstance(entry, dict)
                or set(entry) != {'source_id', 'group_ids', 'new_group_paths'}
                or type(entry.get('source_id')) is not int):
            raise ValidationError('无效的频道分组。')
        source_id = entry['source_id']
        if source_id in seen_sources:
            raise ValidationError('频道不可重复。')
        seen_sources.add(source_id)
        if source_id not in proposal.source_ids:
            raise NotFound()
        group_ids = validated_ids(entry['group_ids'], 3)
        if len(group_ids) != len(entry['group_ids']):
            raise ValidationError('子分组不可重复。')
        if not set(group_ids) <= owned_group_ids & allowed_group_ids:
            raise NotFound()
        paths = entry['new_group_paths']
        if not isinstance(paths, list) or len(paths) > 3:
            raise ValidationError('建议的新分组路径无效。')
        normalized_paths = []
        for path in paths:
            path_digest = digest(path)
            if path_digest not in allowed_paths or path != allowed_paths[path_digest]:
                raise ValidationError('只能应用本次 AI 预览建议的新分组路径。')
            if path_digest in {digest(item) for item in normalized_paths}:
                raise ValidationError('新分组路径不可重复。')
            normalized_paths.append(path)
            requested_paths[path_digest] = path
        if not group_ids and not normalized_paths:
            raise ValidationError('每个频道至少选择一个子分组。')
        if len(group_ids) + len(normalized_paths) > 3:
            raise ValidationError('每个频道最多属于三个子分组。')
        normalized.append((source_id, group_ids, normalized_paths))
    if len(requested_paths) > 8:
        raise ValidationError('一次最多创建八个新分组路径。')

    subscriptions = {
        subscription.source_id: subscription
        for subscription in ChannelSubscription.objects.filter(
            user=user, source_id__in=seen_sources,
        ).prefetch_related('groups')
    }
    if len(subscriptions) != len(seen_sources):
        raise NotFound()
    for source_id, group_ids, paths in normalized:
        existing = {group.pk for group in subscriptions[source_id].groups.all()}
        if len(existing | set(group_ids)) + len(paths) > 3:
            raise ValidationError('每个频道最多属于三个子分组。')

    existing_roots = {
        root.pk: root for root in ChannelGroupRoot.objects.filter(
            user=user,
            pk__in={path['root_id'] for path in requested_paths.values() if path['root_id'] is not None},
        )
    }
    expected_root_ids = {
        path['root_id'] for path in requested_paths.values() if path['root_id'] is not None
    }
    if set(existing_roots) != expected_root_ids:
        raise NotFound()
    new_root_names = {
        path['root_name'] for path in requested_paths.values() if path['root_name'] is not None
    }
    child_names = {path['name'] for path in requested_paths.values()}
    if ChannelGroupRoot.objects.filter(user=user).count() + len(new_root_names) > 40:
        raise ValidationError('每个账号最多创建 40 个根分类。')
    if ChannelGroup.objects.filter(user=user).count() + len(child_names) > 200:
        raise GroupLimitExceeded()
    if (ChannelGroupRoot.objects.filter(user=user, name__in=new_root_names).exists()
            or ChannelGroup.objects.filter(user=user, name__in=child_names).exists()):
        raise GroupingConflict('分组层级已变化，请重新生成预览。')

    created_roots = {}
    created_groups = {}
    touched_roots = set()
    for path_digest, path in requested_paths.items():
        root = existing_roots.get(path['root_id'])
        if root is None:
            root = created_roots.get(path['root_name'])
            if root is None:
                root = ChannelGroupRoot.objects.create(user=user, name=path['root_name'])
                created_roots[path['root_name']] = root
        group = ChannelGroup.objects.create(user=user, root=root, name=path['name'])
        created_groups[path_digest] = group
        touched_roots.add(root.pk)
    if touched_roots or created_roots:
        record_group_structure_change(
            user, root_ids=touched_roots, exclude_proposal_id=proposal.pk,
        )

    changes = []
    for source_id, group_ids, paths in normalized:
        subscription = subscriptions[source_id]
        selected_group_ids = group_ids + [created_groups[digest(path)].pk for path in paths]
        for group_id in selected_group_ids:
            if ChannelGroupingOverride.objects.filter(
                user=user, source_id=source_id, group_id=group_id, suppressed=True,
            ).exists():
                continue
            member, created = ChannelGroupMember.objects.get_or_create(
                group_id=group_id, subscription=subscription,
            )
            if created:
                changes.append({
                    'member_id': member.pk, 'source_id': source_id, 'group_id': group_id,
                })
        SubscriptionGroupingState.objects.update_or_create(
            subscription=subscription, defaults={'status': 'applied'},
        )
    proposal.status, proposal.applied_at, proposal.applied_changes = 'applied', timezone.now(), changes
    proposal.save(update_fields=['status', 'applied_at', 'applied_changes'])
    return proposal


def subscription_signature(subscription, cfg, groups=None):
    profile = profile_data(subscription.source)
    if not (cfg.match_existing or cfg.ai_enabled):
        return digest([profile['evidence_hash'], profile['topics'], profile['origin'], cfg.revision])
    return digest([evidence_for(subscription.source), groups if groups is not None else private_groups(subscription.user), cfg.revision])


def process_personal_subscription(subscription, cfg, *, groups=None):
    user = subscription.user
    state, _ = SubscriptionGroupingState.objects.get_or_create(subscription=subscription)
    if state.status == 'applied' or subscription.groups.exists():
        return
    groups = private_groups(user) if groups is None else groups
    signature = subscription_signature(subscription, cfg, groups)
    if state.profile_hash == signature:
        return
    evidence = evidence_for(subscription.source)
    result = group_results(user, [subscription.source], [evidence], groups)[0]
    state.profile_hash = signature
    state.status = 'pending'
    if cfg.match_existing and result['group_ids']:
        now = timezone.now()
        changes = []
        reliable = not result['needs_review'] and result['origin'] in {'policy', 'catalog', 'manual'}
        if cfg.mode == 'auto' and reliable:
            for group_id in result['group_ids']:
                member, created = ChannelGroupMember.objects.get_or_create(group_id=group_id, subscription=subscription)
                if created:
                    changes.append({'member_id': member.pk, 'source_id': subscription.source_id, 'group_id': group_id})
            state.status = 'applied'
        else:
            state.status = 'suggested'
        ChannelGroupingProposal.objects.create(user=user, engine='rules', target='groups', background=True,
            status='applied' if state.status == 'applied' else 'ready', source_ids=[subscription.source_id],
            input_snapshot=snapshot(user, [subscription.source_id], 'groups'), evidence=[evidence], group_snapshot=groups,
            result=[result], applied_at=now if changes else None, applied_changes=changes, expires_at=now + timedelta(days=1))
    state.save()
    return state.status == 'applied'
