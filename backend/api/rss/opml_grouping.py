"""Deterministic personal grouping from explicit OPML paths or local catalog URLs.

No inference, network calls, catalog publication or subscription admission here.
The caller holds the owner's writer reservation for preview and confirmation.
"""
from hashlib import sha256
import json

from django.db.models import F
from rest_framework.exceptions import ValidationError

from api.models import ChannelGroup, ChannelGroupMember, ChannelGroupRoot, ChannelSubscription
from api.rss.catalog_taxonomy import paths_for_tags
from api.rss.directory_models import FeedDirectoryEntry, FeedDirectorySnapshot
from api.rss.http import RssConflict
from api.services.channel_grouping import record_group_structure_change
from api.smart_channel_models import ChannelGroupingConfig, ChannelGroupingOverride


def grouping_snapshot(user):
    """Include membership (not only structure versions) to fence manual edits."""
    state = [
        list(ChannelGroupRoot.objects.filter(user=user).order_by('pk').values_list('pk', 'name', 'version')),
        list(ChannelGroup.objects.filter(user=user).order_by('pk').values_list('pk', 'root_id', 'name', 'version')),
        list(ChannelSubscription.objects.filter(user=user).order_by('pk').values_list('pk', 'source_id', 'created_at')),
        list(ChannelGroupMember.objects.filter(subscription__user=user).order_by('pk').values_list('pk', 'group_id', 'subscription_id')),
        list(ChannelGroupingOverride.objects.filter(user=user).order_by('pk').values_list('pk', 'source_id', 'group_id', 'suppressed', 'touched_at')),
        list(FeedDirectorySnapshot.objects.filter(active=True).values_list('pk', 'checksum')),
        list(ChannelGroupingConfig.objects.filter(user=user).values_list('revision', flat=True)),
        list(ChannelSubscription.objects.filter(user=user).order_by('pk', 'source__feed_links__pk').values_list(
            'pk', 'source__feed_links__binding_id', 'source__feed_links__enabled',
            'source__feed_links__association_policy', 'source__feed_links__binding__canonical_feed_url',
            'source__feed_links__binding__effective_feed_url')),
    ]
    return sha256(json.dumps(state, default=str, sort_keys=True).encode()).hexdigest()


def catalog_paths(urls):
    from api.rss.opml import _group_path_key
    result = {}
    entries = FeedDirectoryEntry.objects.filter(snapshot__active=True, visibility='public', kind='feed', public_url__in=urls)
    for entry in entries:
        result.setdefault(entry.public_url, set()).update(
            _group_path_key((path['section_label'], path['group_label'])) for path in paths_for_tags(entry.tags)
        )
    return result


def prepare_rows(user, rows, *, organize_existing=False):
    """Only add existing owner subscriptions, never the whole public directory."""
    explicit = {row['feed_url']: set(row['groups']) for row in rows if row['feed_url']}
    subscriptions = list(ChannelSubscription.objects.filter(user=user).select_related('source').prefetch_related(
        'groups', 'source__feed_links__binding').order_by('pk'))
    by_url = {}
    for subscription in subscriptions:
        for link in subscription.source.feed_links.all():
            if not link.enabled or link.association_policy != {'version': 1, 'mode': 'all'}:
                continue
            for url in (link.binding.canonical_feed_url, link.binding.effective_feed_url):
                if url:
                    by_url.setdefault(url, {})[subscription.pk] = subscription
    directory = catalog_paths(set(by_url) | set(explicit))
    if organize_existing:
        if len(subscriptions) > 500:
            raise ValidationError('当前已有订阅超过500项，本次整理上限为500项。')
        # Confirmed owner uploads are explicit evidence, never inferred titles.
        from api.rss.import_models import RssImportItem
        previous = RssImportItem.objects.filter(batch__user=user, batch__removed_at__isnull=True,
            batch__cancelled_at__isnull=True, feed_url__in=by_url,
            subscription__user=user, status='succeeded').exclude(
                batch__confirmed_request_hash='').order_by('pk')
        for item in previous:
            if item.feed_url not in explicit:
                directory.setdefault(item.feed_url, set()).update(item.groups)
    represented = set()
    existing_rows = {}
    for row in rows:
        matches = list(by_url.get(row['feed_url'], {}).values())
        # Ambiguous source identity cannot authorize an existing relationship edit.
        if len(matches) > 1:
            row['outcome'] = 'already_subscribed'
            row['groups'] = []
            continue
        subscription = matches[0] if matches else None
        if subscription:
            represented.add(subscription.pk)
            row['subscription_id'] = subscription.pk
            row['outcome'] = 'already_subscribed'
        if not row['groups']:
            row['groups'] = sorted(directory.get(row['feed_url'], set()))
        if subscription:
            if subscription.pk in existing_rows:
                prior = existing_rows[subscription.pk]
                prior['groups'] = sorted(set(prior['groups']) | set(row['groups']))
                row['groups'] = []
            else:
                existing_rows[subscription.pk] = row
    if organize_existing:
        for subscription in subscriptions:
            if subscription.pk in represented or subscription.groups.all():
                continue
            urls = sorted(url for url, matches in by_url.items() if subscription.pk in matches and len(matches) == 1)
            paths = set()
            for url in urls:
                paths.update(explicit.get(url) or directory.get(url, set()))
            rows.append(dict(feed_url=urls[0] if urls else '', title=subscription.source.name, groups=sorted(paths),
                             status='preview', duplicate_count=0, subscription_id=subscription.pk,
                             outcome='already_subscribed'))
    # Import and organization each remain bounded; do not silently truncate.
    if len(rows) > 1000:
        raise ValidationError('一次预览最多包含500个导入项和500个已有订阅，请分批整理。')
    return rows


def group_plan(user, labels):
    from api.rss.opml import _group_path_parts
    roots = {root.name: root for root in ChannelGroupRoot.objects.filter(user=user)}
    children = {group.name: group for group in ChannelGroup.objects.filter(user=user).select_related('root')}
    paths = {}
    for label in labels:
        parts = _group_path_parts(label)
        paths[label] = parts
    child_roots = {}
    for parts in paths.values():
        if len(parts) in (1, 2):
            child_roots.setdefault(parts[-1], set()).add(parts[0] if len(parts) == 2 else None)
    result = {}
    for label, parts in paths.items():
        reason = ''
        root_name = parts[0] if len(parts) == 2 else None
        if len(parts) not in (1, 2):
            reason = '超过两级层级，请手动选择目标分组'
        elif any(not 1 <= len(name.strip()) <= 40 or name != name.strip() or
                 any(ord(c) < 32 or ord(c) == 127 for c in name) for name in parts):
            reason = '组名须为1–40字符且无首尾空格或控制字符，请手动映射'
        elif len(child_roots[parts[-1]]) > 1:
            reason = '文件内同名子分组位于不同栏目，请手动映射'
        child = children.get(parts[-1])
        if not reason and child and (child.root.name if child.root_id else None) != root_name:
            reason = '已有同名分组的父分类不同，不会移动；请手动映射，或在分组管理预览确认结构调整'
        result[label] = {'root_name': root_name, 'name': parts[-1],
                         'action': 'conflict' if reason else ('reuse' if child else 'create'),
                         'group_id': child.pk if child and not reason else None,
                         'create_root': root_name is not None and root_name not in roots, 'reason': reason}
    return result


def resolve_auto_groups(user, labels, plan):
    if not labels:
        return {}
    if any(label not in plan or plan[label]['action'] == 'conflict' for label in labels):
        raise ValidationError('自动分组存在冲突，请手动映射或保留未分组。')
    paths = [plan[label] for label in labels]
    roots = {root.name: root for root in ChannelGroupRoot.objects.filter(user=user)}
    groups = {group.name: group for group in ChannelGroup.objects.filter(user=user)}
    if len(roots) + len({p['root_name'] for p in paths if p['root_name'] is not None} - roots.keys()) > 40:
        raise ValidationError('每个账号最多创建 40 个根分类，请减少所选分组。')
    if len(groups) + len({p['name'] for p in paths} - groups.keys()) > 200:
        raise ValidationError('每个账号最多创建 200 个子分组，请减少所选分组。')
    resolved, touched, created = {}, set(), False
    for label in sorted(labels):
        path = plan[label]
        root = roots.get(path['root_name'])
        if root is None and path['root_name'] is not None:
            root = ChannelGroupRoot.objects.create(user=user, name=path['root_name'])
            roots[root.name] = root
        group = groups.get(path['name'])
        if group is None:
            group = ChannelGroup.objects.create(user=user, root=root, name=path['name'])
            groups[group.name] = group
            created = True
            if root:
                touched.add(root.pk)
        if group.root_id != (root.pk if root else None):
            raise RssConflict('分组层级已变化，请重新预览。')
        resolved[label] = group.pk
    if created:
        record_group_structure_change(user, root_ids=touched)
    return resolved


def apply_existing_groups(user, item, group_ids):
    subscription = ChannelSubscription.objects.get(pk=item.subscription_id, user=user)
    if subscription.groups.exists():
        raise RssConflict('订阅已手动归组，请重新预览。')
    suppressed = set(ChannelGroupingOverride.objects.filter(user=user, source_id=subscription.source_id,
        suppressed=True).values_list('group_id', flat=True))
    if suppressed & set(group_ids):
        raise RssConflict('所选分组曾被手动排除，请先调整个人分组设置。')
    ChannelGroupMember.objects.bulk_create([
        ChannelGroupMember(subscription=subscription, group_id=group_id) for group_id in group_ids
    ])
    ChannelGroup.objects.filter(user=user, pk__in=group_ids).update(version=F('version') + 1)
    item.status, item.outcome = 'succeeded', 'organized'
