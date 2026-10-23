"""Real data endpoints for the NewsHub reading and channel workspace."""
from datetime import timedelta
import ipaddress
from urllib.parse import urlsplit, parse_qsl, urlencode
from django.conf import settings
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from api.rss.access import authorized_news, authorized_sources, news_in_sources, article_sources, with_authorized_source_counts
from api.models import Source, News, NewsSourceItem, BlockedNews, ChannelGroup, ChannelSubscription
from api.channel_views import PersonalChannelsView, ChannelSubscriptionsView, ChannelGroupDetailView, ids
from api.smart_channel_models import (SourceTopicProfile, ChannelGroupingConfig, ChannelGroupingProposal,
    ChannelClassifierSettings, ReadingDay, ChannelIntakeRequest, SubscriptionGroupingState)
from api.services.channel_topics import TOPICS, PRESETS, TOPIC_MAP, channel_articles, profile_data, base_profile
from api.services.channel_grouping import (lock_user, config_data, credential_fingerprint, make_proposal, apply_proposal,
    undo_proposal, proposal_data, validated_mode, validated_topics, GroupingConflict, mark_manual, process_subscription)


class WorkspaceThrottle(SimpleRateThrottle):
    scope = 'channel_workspace'
    rate = '60/min'
    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk if request.user.is_authenticated else self.get_ident(request)}


class PrivateWorkspaceView(PersonalChannelsView):
    throttle_classes = [WorkspaceThrottle]
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if settings.PUBLIC_SITE_MODE != 'full':
            raise PermissionDenied('当前站点为只读模式。')


class CatalogView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        profiles = {p.source_id: p for p in SourceTopicProfile.objects.all()}
        catalog = []
        from api.services.channel_catalog import catalog_sources
        sources = catalog_sources(request.user, request.query_params.get('purpose', 'history'))
        for source in with_authorized_source_counts(request.user, sources).select_related('publication').order_by('name'):
            data = profile_data(source, profiles.get(source.pk, False))
            data.update(name=source.publication.display_name or source.name, reading_policy=source.publication.reading_policy)
            data['news_count'] = source.rss_news_count
            catalog.append(data)
        return Response({'topics': TOPICS, 'presets': PRESETS, 'sources': catalog}, headers={'Cache-Control': 'private, no-store'})


class SourceProfileView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [WorkspaceThrottle]
    def get(self, request, pk):
        source = get_object_or_404(authorized_sources(request.user).select_related('publication'), pk=pk)
        data = profile_data(source)
        data.update(name=source.publication.display_name or source.name, reading_policy=source.publication.reading_policy)
        articles = news_in_sources(authorized_news(request.user), Source.objects.filter(pk=source.pk)).select_related('source')
        if request.user.is_authenticated:
            articles = articles.exclude(id__in=BlockedNews.objects.filter(user=request.user).values('news_id'))
        data['news_count'] = articles.count()
        data['recent_articles'] = list(articles.order_by('-publish_time').values('id', 'title', 'publish_time')[:8])
        return Response(data, headers={'Cache-Control': 'private, no-store'})

    @transaction.atomic
    def patch(self, request, pk):
        if settings.PUBLIC_SITE_MODE != 'full' or not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
            raise PermissionDenied()
        lock_user(request.user)
        source = get_object_or_404(Source, pk=pk)
        if not isinstance(request.data, dict):
            raise ValidationError('请求应为 JSON 对象。')
        if not any(key in request.data for key in ('topics', 'description')):
            raise ValidationError('请提供需要修改的简介或主题。')
        stored = SourceTopicProfile.objects.filter(source=source).first()
        effective = profile_data(source, stored)
        # PATCH must preserve the *effective* value of fields not supplied.
        # Otherwise updating just one field silently erases the other.
        topics = request.data.get('topics', effective['topics'])
        if topics:
            topics = validated_topics(topics)
        elif not isinstance(topics, list):
            raise ValidationError('无效主题。')
        about = request.data.get('description', effective['description'])
        if not isinstance(about, str) or len(about) > 1000:
            raise ValidationError('简介最多 1000 字。')
        about = about.strip()
        # An unchanged PATCH explicitly reaffirms metadata after a source identity change.
        if (stored and stored.origin == 'manual' and stored.topics == topics and
                stored.about == about and stored.evidence_hash == base_profile(source)['evidence_hash']):
            return Response(profile_data(source, stored))
        SourceTopicProfile.objects.update_or_create(source=source, defaults={
            'about': about, 'topics': topics, 'origin': 'manual',
            'evidence_hash': base_profile(source)['evidence_hash'], 'revision': stored.revision + 1 if stored else 1})
        return Response(profile_data(source))


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise ValidationError('请输入有效的网站或 RSS 地址。')
    value = value.strip()
    try:
        URLValidator(schemes=['http', 'https'])(value)
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 80, 443):
            raise ValueError()
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (ValueError, DjangoValidationError):
        raise ValidationError('只接受不含凭据的公开 HTTP(S) 域名地址。') from None
    return value, host.removeprefix('www.'), parsed.path.rstrip('/'), urlencode(sorted(parse_qsl(parsed.query)))


class ResolveChannelView(PrivateWorkspaceView):
    def post(self, request):
        value, host, path, query = normalize_url(request.data.get('url'))
        exact, publisher = [], []
        for source in authorized_sources(request.user):
            data = profile_data(source)
            for address in [source.url, data['feed_url']]:
                if not address:
                    continue
                try:
                    _, candidate_host, candidate_path, candidate_query = normalize_url(address)
                except ValidationError:
                    continue
                if candidate_host == host:
                    publisher.append(data)
                    if candidate_path == path and candidate_query == query:
                        exact.append(data)
        # Whole-site roots can legitimately resolve to several reviewed subchannels.
        matches = exact or (publisher if not path and not query else [])
        unique = {item['id']: item for item in matches}
        return Response({'matches': list(unique.values()), 'supported': bool(unique),
            'message': '请选择要订阅的已登记频道。' if unique else '此地址尚未登记，可提交接入申请；不会立即抓取或订阅。', 'url': value})


class IntakeView(PrivateWorkspaceView):
    def get(self, request):
        return Response(list(ChannelIntakeRequest.objects.filter(user=request.user).order_by('-created_at').values('id', 'url', 'status', 'created_at')[:30]))
    @transaction.atomic
    def post(self, request):
        lock_user(request.user)
        url, _, _, _ = normalize_url(request.data.get('url'))
        if any(k.lower() in {'token', 'key', 'api_key', 'access_token', 'password'} for k, _ in parse_qsl(urlsplit(url).query)):
            raise ValidationError('接入申请不能包含私有令牌。')
        if ChannelIntakeRequest.objects.filter(user=request.user, created_at__date=timezone.localdate()).count() >= 10:
            raise Throttled(3600, '已达到今日接入申请上限。')
        item, created = ChannelIntakeRequest.objects.get_or_create(user=request.user, url=url)
        return Response({'id': item.pk, 'url': item.url, 'status': item.status}, status=201 if created else 200)



class GroupingConfigView(PrivateWorkspaceView):
    def get(self, request):
        data = config_data(request.user)
        data['ai_available'] = settings.PUBLIC_AI_ENABLED and getattr(settings, 'AI_BYOK_ENABLED', False) and bool(credential_fingerprint(request.user))
        cfg = ChannelGroupingConfig.objects.filter(user=request.user).first()
        data['error_code'] = cfg.last_error_code if cfg else ''
        states = SubscriptionGroupingState.objects.filter(subscription__user=request.user)
        data['summary'] = {status: states.filter(status=status).count() for status in ('pending', 'suggested', 'applied')}
        return Response(data)
    @transaction.atomic
    def patch(self, request):
        lock_user(request.user)
        cfg, _ = ChannelGroupingConfig.objects.get_or_create(user=request.user)
        before = config_data(request.user)
        old_snapshot = cfg.execution_snapshot
        cfg.mode = validated_mode(request.data.get('mode', cfg.mode))
        for key in ('match_existing', 'ai_enabled'):
            if key in request.data:
                if type(request.data[key]) is not bool:
                    raise ValidationError('整理开关必须为布尔值。')
                setattr(cfg, key, request.data[key])
        limit = request.data.get('daily_limit', cfg.daily_limit)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValidationError('每日 AI 上限应为 1–20。')
        cfg.daily_limit = limit
        if cfg.ai_enabled and (not before['ai_enabled'] or 'model_config_id' in request.data):
            if request.data.get('consent') is not True or not isinstance(request.data.get('model_config_id'), str):
                raise ValidationError('开启后台 AI 需要明确同意并选择已验证的个人模型。')
            from api.services.channel_model import capture_model, ClassificationAuthorizationChanged
            try:
                cfg.execution_snapshot = capture_model(request.user, scope='personal', model_config_id=request.data['model_config_id'])
            except ClassificationAuthorizationChanged:
                raise ValidationError('个人模型授权不可用，请重新选择。') from None
            cfg.ai_model_id = request.data['model_config_id']
        if not cfg.ai_enabled:
            cfg.execution_snapshot, cfg.ai_model_id = {}, None
        bindings = request.data.get('bindings', before['bindings'])
        if not isinstance(bindings, dict) or len(bindings) > len(TOPIC_MAP):
            raise ValidationError('无效的主题绑定。')
        for key, group_id in bindings.items():
            if key not in TOPIC_MAP or type(group_id) is not int:
                raise ValidationError('无效的主题绑定。')
            if not ChannelGroup.objects.filter(pk=group_id, user=request.user).exists():
                raise NotFound()
        cfg.bindings = bindings
        if cfg.mode != 'off' and (cfg.match_existing or cfg.ai_enabled) and cfg.personal_active_since is None:
            cfg.personal_active_since = timezone.now()
        changed = any(getattr(cfg, key) != before[key] for key in ('mode', 'bindings', 'match_existing', 'ai_enabled', 'ai_model_id', 'daily_limit')) or cfg.execution_snapshot != old_snapshot
        if changed:
            cfg.revision += 1
            cfg.scan_cursor = 0
        cfg.save()
        if changed:
            ChannelGroupingProposal.objects.filter(user=request.user, background=True, engine='ai', status__in=['queued', 'running']).update(
                status='cancelled', error_code='configuration_changed', lease_token='', lease_until=None)
        return self.get(request)


class ProposalsView(PrivateWorkspaceView):
    page_size = 30
    def get(self, request):
        target = request.query_params.get('target')
        if target is not None and target not in ('groups', 'topics', 'hierarchy'):
            raise ValidationError('无效的整理目标。')
        raw_page = request.query_params.get('page', '1')
        if len(raw_page) > 5 or not raw_page.isascii() or not raw_page.isdecimal() or not 1 <= int(raw_page) <= 10000:
            raise ValidationError('页码应为 1–10000 的整数。')
        page = int(raw_page)
        items = ChannelGroupingProposal.objects.filter(user=request.user, public_source__isnull=True)
        if target is not None:
            items = items.filter(target=target)
        # The page size is fixed by the server, and the (created_at, id) order is
        # stable so paging never shows a record twice or skips an older one.
        offset = (page - 1) * self.page_size
        results = [proposal_data(item) for item in items.order_by('-created_at', '-id')[offset:offset + self.page_size]]
        total = items.count()
        return Response({'results': results, 'page': page, 'page_size': self.page_size,
                         'count': total, 'has_more': offset + len(results) < total})
    def post(self, request):
        proposal = make_proposal(request.user, request.data)
        return Response(proposal_data(proposal), status=202 if proposal.status == 'queued' else 201)


class ProposalView(PrivateWorkspaceView):
    def get(self, request, pk):
        proposal = get_object_or_404(ChannelGroupingProposal, pk=pk, user=request.user, public_source__isnull=True)
        return Response(proposal_data(proposal))


class ApplyProposalView(PrivateWorkspaceView):
    def post(self, request, pk):
        return Response(proposal_data(apply_proposal(request.user, pk, request.data)))


class CancelProposalView(PrivateWorkspaceView):
    @transaction.atomic
    def post(self, request, pk):
        lock_user(request.user)
        proposal = get_object_or_404(ChannelGroupingProposal, pk=pk, user=request.user, public_source__isnull=True)
        if proposal.status in {'applied', 'undone'}:
            raise GroupingConflict('已应用的建议请使用撤销。')
        proposal.status, proposal.lease_token, proposal.error_code = 'cancelled', '', 'user_cancelled'
        proposal.save(update_fields=['status', 'lease_token', 'error_code'])
        return Response(proposal_data(proposal))


class UndoProposalView(PrivateWorkspaceView):
    def post(self, request, pk):
        return Response(proposal_data(undo_proposal(request.user, pk)))


class SiteClassifierView(PrivateWorkspaceView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_superuser:
            raise PermissionDenied()
    def get(self, request):
        cfg = ChannelClassifierSettings.objects.select_related('owner').filter(pk=1).first()
        from api.services.channel_ai import classifier_status
        jobs = ChannelGroupingProposal.objects.filter(public_source__isnull=False).order_by('-created_at')[:20]
        return Response({'enabled': bool(cfg and cfg.enabled), 'is_owner': bool(cfg and cfg.owner_id == request.user.pk),
            'daily_limit': cfg.daily_limit if cfg else 10,
            'model_id': cfg.execution_snapshot.get('model', {}).get('model_id') if cfg else None,
            'runtime': classifier_status(cfg),
            'jobs': [proposal_data(j) for j in jobs],
            'intake_requests': list(ChannelIntakeRequest.objects.order_by('-created_at').values('id', 'url', 'status', 'created_at')[:30])})
    @transaction.atomic
    def patch(self, request):
        lock_user(request.user)
        if not isinstance(request.data, dict):
            raise ValidationError('请求应为 JSON 对象。')
        previous = ChannelClassifierSettings.objects.filter(pk=1).first()
        enabled, limit = request.data.get('enabled'), request.data.get('daily_limit', 10)
        if type(enabled) is not bool or type(limit) is not int or not 1 <= limit <= 20:
            raise ValidationError('请选择开关与每日 1–20 个任务的预算。')
        if enabled and (request.data.get('consent') is not True or not settings.PUBLIC_AI_ENABLED or not credential_fingerprint(request.user)):
            raise ValidationError('开启前须同意使用本管理员的模型额度，并配置有效的模型连接。')
        execution_snapshot = {}
        if enabled:
            from api.services.channel_model import capture_model, ClassificationAuthorizationChanged
            try:
                execution_snapshot = capture_model(request.user, scope='site', model_config_id=request.data.get('model_config_id'))
            except ClassificationAuthorizationChanged:
                raise ValidationError('请先配置并验证个人默认模型，再明确授权站点后台分类；不会借用其他人的模型。') from None
        must_stop = (not enabled or previous is None or previous.owner_id != request.user.pk
                     or previous.execution_snapshot != execution_snapshot or limit < previous.daily_limit)
        ChannelClassifierSettings.objects.update_or_create(pk=1, defaults={
            'owner': request.user, 'enabled': enabled, 'daily_limit': limit, 'execution_snapshot': execution_snapshot})
        if must_stop:
            # Same short transaction as the grant change: old workers lose CAS
            # authority immediately; no private proposal or applied history changes.
            ChannelGroupingProposal.objects.filter(engine='ai', public_source__isnull=False,
                status__in=['queued', 'running']).update(
                    status='cancelled', error_code='classifier_stopped', lease_token='', lease_until=None)
        return self.get(request)


class SmartSubscriptionsView(ChannelSubscriptionsView):
    @transaction.atomic
    def post(self, request):
        lock_user(request.user)
        source_ids = ids(request.data, 'source_ids')
        before = {s.source_id: set(s.groups.values_list('id', flat=True)) for s in ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids).prefetch_related('groups')}
        response = super().post(request)
        action = request.data.get('action', 'subscribe')
        if action in {'set_groups', 'add_to_group', 'move_to_group', 'remove_from_group'}:
            for subscription in ChannelSubscription.objects.filter(user=request.user, source_id__in=source_ids).prefetch_related('groups'):
                previous = before.get(subscription.source_id, set())
                after = set(subscription.groups.values_list('pk', flat=True))
                # Explicit remove of an absent member is still a suppression.
                if action == 'remove_from_group':
                    previous = previous | {request.data['group_id']}
                mark_manual(request.user, subscription.source_id, previous, after)
        if action == 'subscribe':
            for subscription in ChannelSubscription.objects.filter(user=request.user, source_id__in=set(source_ids) - set(before)):
                try:
                    process_subscription(subscription.pk)
                except APIException:
                    # Subscription still succeeds; the worker can retry organization.
                    pass
        return response


class SmartGroupDetailView(ChannelGroupDetailView):
    @transaction.atomic
    def patch(self, request, pk):
        lock_user(request.user)
        group = get_object_or_404(ChannelGroup, pk=pk, user=request.user)
        before = set(group.subscriptions.values_list('source_id', flat=True))
        response = super().patch(request, pk)
        after = set(group.subscriptions.values_list('source_id', flat=True))
        touched = before ^ after
        for key in ('source_ids', 'add_source_ids', 'remove_source_ids'):
            touched.update(request.data.get(key, []))
        for source_id in touched:
            mark_manual(request.user, source_id, {pk} if source_id in before else set(), {pk} if source_id in after else set())
        return response


class ReadingStatsView(PrivateWorkspaceView):
    def get(self, request):
        today = timezone.localdate()
        events = ReadingDay.objects.filter(user=request.user, news_id__in=authorized_news(request.user).values('pk'))
        days = dict(events.filter(day__gte=today - timedelta(days=6)).values('day').annotate(n=Count('news_id', distinct=True)).values_list('day', 'n'))
        cursor = today if events.filter(day=today).exists() else today - timedelta(days=1)
        streak = 0
        for day in events.values_list('day', flat=True).distinct().order_by('-day')[:366]:
            if day == cursor:
                streak += 1
                cursor -= timedelta(days=1)
            elif day < cursor:
                break
        return Response({'today': days.get(today, 0), 'total': events.values('news_id').distinct().count(), 'streak': streak,
            'timezone': settings.TIME_ZONE, 'week': [{'day': (today - timedelta(days=i)).isoformat(), 'count': days.get(today - timedelta(days=i), 0)} for i in range(6, -1, -1)]})
    def post(self, request):
        news_id = request.data.get('news_id')
        if type(news_id) is not int or news_id <= 0:
            raise ValidationError('无效新闻 ID。')
        if BlockedNews.objects.filter(user=request.user, news_id=news_id).exists():
            raise NotFound()
        news = get_object_or_404(authorized_news(request.user), pk=news_id)
        ReadingDay.objects.get_or_create(user=request.user, news=news, day=timezone.localdate())
        return Response({'recorded': True})
    def delete(self, request):
        ReadingDay.objects.filter(user=request.user).delete()
        return Response(status=204)


class DashboardView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        news = authorized_news(request.user).filter(related_to__isnull=True, publish_time__lte=timezone.now()).select_related('source')
        if request.user.is_authenticated:
            news = news.exclude(id__in=BlockedNews.objects.filter(user=request.user).values('news_id'))
        ranked = ReadingDay.objects.filter(day__gte=timezone.localdate() - timedelta(days=1), news_id__in=news.values('id')).values('news_id').annotate(readers=Count('user_id', distinct=True)).order_by('-readers', '-news_id')[:10]
        ranks = list(ranked)
        if ranks:
            by_id = news.in_bulk([r['news_id'] for r in ranks])
            articles = [by_id[r['news_id']] for r in ranks if r['news_id'] in by_id]
        else:
            articles = list(news.order_by('-publish_time')[:10])
        stories = []
        for article in articles:
            source = article_sources(request.user, article).select_related('publication').first()
            if source is not None:
                stories.append({'id': article.pk, 'title': article.title,
                    'source_name': source.publication.display_name or source.name, 'publish_time': article.publish_time})
        return Response({'kind': 'popular' if ranks else 'latest', 'stories': stories},
            headers={'Cache-Control': 'private, no-store'})
