"""Account-owned reading configuration; all mutations serialize on the user row."""
from collections.abc import Mapping

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from api.models import Source, ChannelSubscription, ChannelGroup, NewsPreference
from api.services.channel_catalog import subscription_status


def ids(data, key):
    value = data.get(key)
    if not isinstance(value, list) or len(value) > 1000 or any(type(x) is not int or x <= 0 for x in value):
        raise ValidationError({key: '需要最多 1000 个正整数 ID。'})
    return set(value)


def group_data(group):
    return {'id': group.id, 'name': group.name, 'source_ids': [subscription.source_id for subscription in group.subscriptions.all()],
            'created_at': group.created_at}


def owned_group(user, pk):
    return get_object_or_404(ChannelGroup, user=user, pk=pk)


def group_name(data, user, exclude=None):
    value = data.get('name')
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
        raise ValidationError({'name': '分组名称去除首尾空格后须为 1–40 字。'})
    value = value.strip()
    if ChannelGroup.objects.filter(user=user, name=value).exclude(pk=exclude).exists():
        raise ValidationError({'name': '已有同名分组。'})
    return value


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
        elif action == 'set_groups':
            group_ids = ids(request.data, 'group_ids')
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
        return self.get(request)


class ChannelGroupsView(PersonalChannelsView):
    def get(self, request):
        return Response([group_data(g) for g in ChannelGroup.objects.filter(user=request.user).prefetch_related('subscriptions')])

    @transaction.atomic
    def post(self, request):
        self.lock(request.user)
        group = ChannelGroup.objects.create(user=request.user, name=group_name(request.data, request.user))
        return Response(group_data(group), status=201)


class ChannelGroupDetailView(PersonalChannelsView):
    def get(self, request, pk):
        return Response(group_data(owned_group(request.user, pk)))

    @transaction.atomic
    def patch(self, request, pk):
        self.lock(request.user)
        group = owned_group(request.user, pk)
        if 'name' in request.data:
            group.name = group_name(request.data, request.user, exclude=pk)
            group.save(update_fields=['name'])
        for key, operation in [('source_ids', 'set'), ('add_source_ids', 'add'), ('remove_source_ids', 'remove')]:
            if key not in request.data: continue
            source_ids = ids(request.data, key)
            subscriptions = list(ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids))
            if len(subscriptions) != len(source_ids):
                raise ValidationError({key: '只能操作自己的已订阅频道。'})
            if operation == 'set':
                group.subscriptions.set(subscriptions)
            else:
                getattr(group.subscriptions, operation)(*subscriptions)
        return Response(group_data(group))

    @transaction.atomic
    def delete(self, request, pk):
        self.lock(request.user)
        group = owned_group(request.user, pk)
        NewsPreference.objects.filter(user=request.user, group=group).update(scope='subscribed', group=None)
        group.delete()
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
