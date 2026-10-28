"""Account-owned reading configuration; all mutations serialize on the user row."""
from collections.abc import Mapping

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, F
from django.shortcuts import get_object_or_404
from django.http import Http404
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from api.models import Source, ChannelSubscription, ChannelGroup, ChannelGroupRoot, NewsPreference
from api.services.channel_catalog import subscription_status
from api.services.channel_grouping import record_group_structure_change


def ids(data, key):
    value = data.get(key)
    if not isinstance(value, list) or len(value) > 1000 or any(type(x) is not int or x <= 0 for x in value):
        raise ValidationError({key: '需要最多 1000 个正整数 ID。'})
    return set(value)


def group_data(group):
    return {
        'id': group.id, 'root_id': group.root_id, 'name': group.name,
        'source_ids': [subscription.source_id for subscription in group.subscriptions.all()],
        'version': group.version, 'created_at': group.created_at, 'updated_at': group.updated_at,
    }


def root_data(root):
    child_count = getattr(root, 'child_count', None)
    if child_count is None:
        child_count = root.children.count()
    return {
        'id': root.id, 'name': root.name, 'version': root.version,
        'child_count': child_count, 'created_at': root.created_at, 'updated_at': root.updated_at,
    }


def owned_group(user, pk):
    return get_object_or_404(ChannelGroup, user=user, pk=pk)


def group_name(data, user, exclude=None, *, model=ChannelGroup):
    value = data.get('name')
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 40
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValidationError({'name': '分组名称去除首尾空格后须为 1–40 字，且不能包含控制字符。'})
    value = value.strip()
    if model.objects.filter(user=user, name=value).exclude(pk=exclude).exists():
        raise ValidationError({'name': '已有同名分组。'})
    return value


class ChannelGroupConflict(APIException):
    status_code = 409
    default_detail = '分组结构已经变化，请刷新后重试。'


def scope_config(data, user):
    scope = data.get('scope', 'all')
    if scope not in {'all', 'subscribed', 'ungrouped', 'group'}:
        raise ValidationError({'scope': '无效的资讯范围。'})
    group = None
    if scope == 'group':
        pk = data.get('group_id')
        try:
            if not str(pk).isdecimal() or int(pk) <= 0:
                raise ValueError
            pk = int(pk)
        except (ValueError, TypeError):
            raise ValidationError({'group_id': '请选择分组。'})
        group = owned_group(user, pk)
    return scope, group


def scoped_sources(user, scope, group=None):
    subscriptions = ChannelSubscription.objects.filter(user=user)
    if scope == 'ungrouped':
        subscriptions = subscriptions.filter(groups__isnull=True)
    elif scope == 'group':
        subscriptions = subscriptions.filter(groups=group)
    return subscriptions.values_list('source_id', flat=True)


class PersonalChannelsView(APIView):
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in {'POST', 'PATCH'} and not isinstance(request.data, Mapping):
            raise ValidationError('请求内容须为 JSON 对象。')

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def lock(self, user):
        User.objects.filter(pk=user.pk).update(last_login=F('last_login'))


class ChannelSubscriptionsView(PersonalChannelsView):
    def get(self, request):
        subscriptions = ChannelSubscription.objects.filter(user=request.user).prefetch_related('groups')
        return Response([{'id': s.id, 'source_id': s.source_id, 'category_id':s.category_id,'category_version':s.category_version,'group_ids': [g.id for g in s.groups.all()]} for s in subscriptions])

    @transaction.atomic
    def post(self, request):
        self.lock(request.user)
        source_ids = ids(request.data, 'source_ids')
        action = request.data.get('action', 'subscribe')
        if action == 'set_category':
            from api.models import Category
            from api.rss.http import RssConflict
            if len(source_ids)!=1 or set(request.data)-{'action','source_ids','category_id','expected_version'}:
                raise ValidationError('请选择一个频道。')
            category_id=request.data.get('category_id');expected=request.data.get('expected_version')
            if type(expected) is not int or expected<0 or (category_id is not None and (type(category_id) is not int or not Category.objects.filter(pk=category_id).exists())):
                raise ValidationError('请选择有效分类并提供当前版本。')
            subscription=ChannelSubscription.objects.filter(user=request.user,source_id=next(iter(source_ids))).first()
            if subscription is None: raise Http404
            if not ChannelSubscription.objects.filter(pk=subscription.pk,category_version=expected).update(category_id=category_id,category_version=F('category_version')+1):
                raise RssConflict('频道分类已经改变，请刷新。')
        elif action == 'unsubscribe':
            from api.rss.subscriptions import unsubscribe
            for subscription_id in list(ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids).values_list('pk', flat=True)):
                unsubscribe(request.user, subscription_id)
        elif action == 'subscribe':
            from api.rss.access import authorized_sources
            sources = list(authorized_sources(request.user).filter(pk__in=source_ids))
            if len(sources) != len(source_ids):
                from rest_framework.exceptions import NotFound
                raise NotFound()
            existing = set(ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids).values_list('source_id', flat=True))
            if any(subscription_status(s)[0] != 'active' for s in sources if s.id not in existing):
                raise ValidationError({'source_ids': '停用频道不能新增订阅。'})
            for source in sources:
                ChannelSubscription.objects.get_or_create(user=request.user, source=source)
                from api.rss.operations import reconcile_binding
                from api.services.channel_catalog import current_feed_links
                for binding_id in current_feed_links(source).values_list('binding_id', flat=True):
                    reconcile_binding(binding_id)
        elif action in {'add_to_group', 'move_to_group', 'remove_from_group'}:
            group_id = request.data.get('group_id')
            if type(group_id) is not int or group_id <= 0 or not source_ids:
                raise ValidationError('请选择有效的分组和频道。')
            group = owned_group(request.user, group_id)
            subscriptions = list(ChannelSubscription.objects.filter(
                user=request.user, source_id__in=source_ids,
            ).prefetch_related('groups'))
            if len(subscriptions) != len(source_ids):
                raise Http404
            if action == 'add_to_group' and any(
                group not in subscription.groups.all() and len(subscription.groups.all()) >= 3
                for subscription in subscriptions
            ):
                raise ValidationError('每个频道最多属于三个子分组。')
            for subscription in subscriptions:
                if action == 'move_to_group':
                    subscription.groups.set([group])
                elif action == 'add_to_group':
                    subscription.groups.add(group)
                else:
                    subscription.groups.remove(group)
        elif action == 'set_groups':
            group_ids = ids(request.data, 'group_ids')
            if len(group_ids) > 3:
                raise ValidationError('每个频道最多属于三个子分组。')
            groups = list(ChannelGroup.objects.filter(user=request.user, pk__in=group_ids))
            if len(groups) != len(group_ids):
                from rest_framework.exceptions import NotFound
                raise NotFound()
            subscriptions = list(ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids))
            if len(subscriptions) != len(source_ids):
                raise ValidationError({'source_ids': '请先订阅频道。'})
            for subscription in subscriptions:
                subscription.groups.set(groups)
        else:
            raise ValidationError({'action': '无效操作。'})
        if action in {'add_to_group', 'move_to_group', 'remove_from_group', 'set_groups'}:
            # Fence even add/remove ABA edits against a pending import preview.
            record_group_structure_change(request.user)
        return self.get(request)


class ChannelGroupRootsView(PersonalChannelsView):
    def get(self, request):
        roots = ChannelGroupRoot.objects.filter(user=request.user).annotate(child_count=Count('children'))
        return Response([root_data(root) for root in roots])

    @transaction.atomic
    def post(self, request):
        self.lock(request.user)
        if set(request.data) != {'name'}:
            raise ValidationError('请只提交根分类名称。')
        if ChannelGroupRoot.objects.filter(user=request.user).count() >= 40:
            raise ValidationError('每个账号最多创建 40 个根分类。')
        root = ChannelGroupRoot.objects.create(
            user=request.user,
            name=group_name(request.data, request.user, model=ChannelGroupRoot),
        )
        record_group_structure_change(request.user)
        return Response(root_data(root), status=201)


class ChannelGroupRootDetailView(PersonalChannelsView):
    def get(self, request, pk):
        root = get_object_or_404(
            ChannelGroupRoot.objects.annotate(child_count=Count('children')),
            user=request.user, pk=pk,
        )
        return Response(root_data(root))

    @transaction.atomic
    def patch(self, request, pk):
        self.lock(request.user)
        if set(request.data) != {'name', 'expected_version'}:
            raise ValidationError('重命名须提交名称与当前版本。')
        root = get_object_or_404(ChannelGroupRoot, user=request.user, pk=pk)
        expected = request.data.get('expected_version')
        if type(expected) is not int or expected < 1:
            raise ValidationError('请提交有效的当前版本。')
        if root.version != expected:
            raise ChannelGroupConflict('根分类已经变化，请刷新后重试。')
        root.name = group_name(request.data, request.user, exclude=pk, model=ChannelGroupRoot)
        root.version += 1
        root.save(update_fields=['name', 'version', 'updated_at'])
        record_group_structure_change(request.user)
        return Response(root_data(root))

    @transaction.atomic
    def delete(self, request, pk):
        self.lock(request.user)
        root = get_object_or_404(ChannelGroupRoot, user=request.user, pk=pk)
        raw_expected = request.query_params.get('expected_version')
        if raw_expected is None or not raw_expected.isascii() or not raw_expected.isdecimal():
            raise ValidationError('请提交有效的当前版本。')
        if root.version != int(raw_expected):
            raise ChannelGroupConflict('根分类已经变化，请刷新后重试。')
        if root.children.exists():
            raise ChannelGroupConflict('根分类仍包含子分组，不能删除。')
        root.delete()
        record_group_structure_change(request.user)
        return Response(status=204)


class ChannelGroupsView(PersonalChannelsView):
    def get(self, request):
        groups = ChannelGroup.objects.filter(user=request.user).prefetch_related('subscriptions')
        return Response([group_data(group) for group in groups])

    @transaction.atomic
    def post(self, request):
        self.lock(request.user)
        if set(request.data) != {'name', 'root_id'} or (request.data['root_id'] is not None and type(request.data['root_id']) is not int):
            raise ValidationError('创建分组须提交名称与根分类ID；直接分组使用空值。')
        if ChannelGroup.objects.filter(user=request.user).count() >= 200:
            raise ValidationError('每个账号最多创建 200 个子分组。')
        root = get_object_or_404(ChannelGroupRoot, user=request.user, pk=request.data['root_id']) if request.data['root_id'] is not None else None
        group = ChannelGroup.objects.create(
            user=request.user, root=root,
            name=group_name(request.data, request.user),
        )
        record_group_structure_change(request.user, root_ids=[root.pk] if root else [])
        return Response(group_data(group), status=201)


class ChannelGroupDetailView(PersonalChannelsView):
    def get(self, request, pk):
        return Response(group_data(owned_group(request.user, pk)))

    @transaction.atomic
    def patch(self, request, pk):
        self.lock(request.user)
        group = owned_group(request.user, pk)
        structural = bool({'name', 'root_id'} & set(request.data))
        if structural:
            if not {'name', 'root_id', 'expected_version'} >= set(request.data) or 'expected_version' not in request.data:
                raise ValidationError('结构调整须提交名称或根分类，以及当前版本。')
            expected = request.data.get('expected_version')
            if type(expected) is not int or expected < 1:
                raise ValidationError('请提交有效的当前版本。')
            if group.version != expected:
                raise ChannelGroupConflict()
            next_root = group.root
            if 'root_id' in request.data:
                if request.data['root_id'] is not None and type(request.data['root_id']) is not int:
                    raise ValidationError('请选择有效的根分类或直接分组。')
                next_root = get_object_or_404(ChannelGroupRoot, user=request.user, pk=request.data['root_id']) if request.data['root_id'] is not None else None
            next_name = group.name
            if 'name' in request.data:
                next_name = group_name(request.data, request.user, exclude=pk)
            next_root_id = next_root.pk if next_root else None
            changed_roots = {group.root_id, next_root_id} if next_root_id != group.root_id else set()
            if next_name != group.name or next_root_id != group.root_id:
                group.name, group.root, group.version = next_name, next_root, group.version + 1
                group.save(update_fields=['name', 'root', 'version', 'updated_at'])
                record_group_structure_change(request.user, root_ids=changed_roots)
            return Response(group_data(group))

        membership_keys = {'source_ids', 'add_source_ids', 'remove_source_ids'}
        if not request.data or set(request.data) - membership_keys:
            raise ValidationError('请提交有效的成员调整。')
        operations = []
        for key, operation in [('source_ids', 'set'), ('add_source_ids', 'add'), ('remove_source_ids', 'remove')]:
            if key not in request.data:
                continue
            source_ids = ids(request.data, key)
            subscriptions = list(ChannelSubscription.objects.filter(
                user=request.user, source_id__in=source_ids,
            ).prefetch_related('groups'))
            if len(subscriptions) != len(source_ids):
                raise ValidationError({key: '只能操作自己的已订阅频道。'})
            if operation in {'set', 'add'} and any(
                group not in subscription.groups.all() and len(subscription.groups.all()) >= 3
                for subscription in subscriptions
            ):
                raise ValidationError('每个频道最多属于三个子分组。')
            operations.append((operation, subscriptions))
        for operation, subscriptions in operations:
            if operation == 'set':
                group.subscriptions.set(subscriptions)
            else:
                getattr(group.subscriptions, operation)(*subscriptions)
        record_group_structure_change(request.user)
        return Response(group_data(group))

    @transaction.atomic
    def delete(self, request, pk):
        self.lock(request.user)
        group = owned_group(request.user, pk)
        root_id = group.root_id
        NewsPreference.objects.filter(user=request.user, group=group).update(scope='subscribed', group=None)
        group_id = group.pk
        group.delete()
        record_group_structure_change(
            request.user, root_ids=[root_id], removed_group_ids=[group_id],
        )
        return Response(status=204)


class NewsPreferencesView(PersonalChannelsView):
    def get(self, request):
        preference = NewsPreference.objects.filter(user=request.user).first()
        scope = preference.scope if preference else 'all'
        if scope == 'group' and not preference.group_id: scope = 'subscribed'
        return Response({'scope': scope, 'group_id': preference.group_id if preference else None})

    @transaction.atomic
    def patch(self, request):
        self.lock(request.user)
        scope, group = scope_config(request.data, request.user)
        NewsPreference.objects.update_or_create(user=request.user, defaults={'scope': scope, 'group': group})
        return self.get(request)
