import logging

from django.db.models import Count, Q
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt, csrf_protect
from rest_framework import generics, filters, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.exceptions import APIException, ValidationError as ApiValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters import rest_framework as django_filters
from .models import Category, Source, News, ChatSession, BlockedNews, ProviderComparison
from .services.chat_history import (
    ChatConflict,
    append_assistant_message,
    append_user_message,
    clear_chat_history,
)
from .authentication import AnonymousCsrfSessionAuthentication
from .services.account_security import (
    AuthSecurityBusy,
    InvalidClientAddress,
    RateLimitExceeded,
    RegistrationUnavailable,
    SignupInviteRequired,
    create_registered_user,
    normalize_email,
    reserve_login_attempts,
    reserve_registration_attempts,
)
from .serializers import (
    CategorySerializer, SourceSerializer,
    NewsListSerializer, NewsDetailSerializer,
    BlockedNewsSerializer,
    ProviderComparisonRunSerializer, ProviderComparisonSerializer,
)
# Module-level import so tests can patch `api.views.get_openai_client`
from api.services.llm_translator import get_openai_client, get_clients, stream_chat
from api.services.article_fetcher import FetchError, fetch_article_markdown
from api.services.chatgpt_subscription import invalidate_authorization_attempts_for_session
from api.crawler_views import IsActiveSuperuser

logger = logging.getLogger(__name__)

# Hardcoded fallback shown when the LLM is unreachable / returns garbage
SUGGESTED_QUESTIONS_FALLBACK = [
    '帮我用一句话总结这篇文章',
    '这篇文章里最重要的三个观点是什么？',
    '有什么背景知识可以帮我更好理解？',
]


# Compatibility import for view-level callers; services never import api.views.
from api.services.article_content import pick_chat_context, context_scope, request_full_content
from api.services.full_content_status import has_full_content, filter_readable_full_content, fetch_eligibility, annotate_full_content_availability


def ensure_full_content(news, execution_guard=None):
    """Compatibility entrypoint: read or enqueue, without article network IO."""
    return request_full_content(news, execution_guard=execution_guard)


class CommaSeparatedIntegerFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class NewsFilter(django_filters.FilterSet):
    category = CommaSeparatedIntegerFilter(method='filter_category')
    source = CommaSeparatedIntegerFilter(method='filter_source')
    region = django_filters.ChoiceFilter(choices=[('domestic', '国内'), ('international', '国际')], method='filter_region')
    source__source_type = django_filters.CharFilter(field_name='source__source_type')
    source_types = django_filters.CharFilter(method='filter_source_types')
    full_content = django_filters.BooleanFilter(
        method='filter_full_content',
    )
    publish_time_after = django_filters.IsoDateTimeFilter(
        field_name='publish_time',
        lookup_expr='gte',
    )

    class Meta:
        model = News
        fields = ['category', 'source', 'source__source_type', 'source_types']

    def filter_source_types(self, queryset, name, value):
        kinds = value.split(',')
        allowed = {kind for kind, _label in Source.TYPE_CHOICES}
        if not 1 <= len(kinds) <= len(allowed) or len(set(kinds)) != len(kinds) or any(kind not in allowed for kind in kinds):
            raise ApiValidationError({'source_types': 'Invalid source type selection.'})
        return queryset.filter(source__source_type__in=kinds)

    def filter_source(self, queryset, name, value):
        from api.services.channel_articles import channel_filter
        return channel_filter(queryset, value)

    def filter_category(self, queryset, name, value):
        from api.services.channel_articles import category_filter
        return category_filter(queryset, value)

    def filter_region(self, queryset, name, value):
        from api.services.channel_articles import region_filter
        return region_filter(queryset, value)

    def filter_full_content(self, queryset, name, value):
        if value:
            from api.services.body_access import can_view_article_body
            return filter_readable_full_content(queryset, privileged=can_view_article_body(getattr(self.request, "user", None)))
        return queryset


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def reciprocal_rank_fusion(*ranked_lists, k=60):
    scores = {}
    for ranked_ids in ranked_lists:
        for rank, nid in enumerate(ranked_ids):
            scores[nid] = scores.get(nid, 0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


class NewsListView(generics.ListAPIView):
    renderer_classes = [JSONRenderer]
    serializer_class = NewsListSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = NewsFilter
    search_fields = ['title', 'content', 'title_zh', 'content_zh']
    ordering_fields = ['publish_time', 'created_at']
    ordering = ['-publish_time']

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store'
        return response

    def get_ordering(self):
        """Map the product-level time sort without mutating DRF's request."""
        if (
            self.request.query_params.get('order_by', '').strip() == 'time'
            and 'ordering' not in self.request.query_params
        ):
            return ['-publish_time']
        return super().get_ordering()

    def get_queryset(self):
        qs = annotate_full_content_availability(News.objects.select_related('source', 'category').prefetch_related('source_items')).defer(
            'full_content', 'full_content_zh', 'full_content_provenance')
        # Hide duplicates by default
        if self.request.query_params.get('include_dupes', 'false') != 'true':
            qs = qs.filter(related_to__isnull=True)
        # Exclude blocked news for authenticated users
        if self.request.user.is_authenticated:
            blocked_ids = BlockedNews.objects.filter(
                user=self.request.user,
            ).values_list('news_id', flat=True)
            qs = qs.exclude(pk__in=blocked_ids)
        from api.channel_views import scope_config, scoped_sources
        scope = self.request.query_params.get('scope', 'all')
        if scope != 'all':
            from rest_framework.exceptions import NotAuthenticated, PermissionDenied
            if settings.PUBLIC_SITE_MODE == 'read_only':
                raise PermissionDenied('当前站点仅支持全部资讯。')
            if not self.request.user.is_authenticated:
                raise NotAuthenticated('请登录后使用个人资讯范围。')
        scope, group = scope_config(self.request.query_params, self.request.user)
        if scope != 'all':
            from api.services.channel_articles import channel_filter
            qs = channel_filter(qs, scoped_sources(self.request.user, scope, group))
        return qs

    def visible_queryset(self):
        # SearchFilter belongs only to the keyword arm, never the vector arm.
        return django_filters.DjangoFilterBackend().filter_queryset(self.request, self.get_queryset(), self)

    def list(self, request, *args, **kwargs):
        representation = request.query_params.get('representation', 'summary')
        if representation != 'summary':
            raise ApiValidationError({'representation': 'Only summary is supported; use the detail endpoint for complete content.'})
        self.visible_queryset()  # Validate reading conditions before service fallback.
        search_query = request.query_params.get('search', '').strip()
        mode = request.query_params.get('mode', 'keyword').strip()

        if not search_query or mode == 'keyword':
            return self._decorate_search_response(
                super().list(request, *args, **kwargs),
                requested=mode if search_query else 'keyword',
                applied='keyword',
            )

        try:
            if mode == 'semantic':
                response = self._semantic_search(request, search_query)
            else:
                response = self._hybrid_search(request, search_query)
        except APIException:
            raise
        except Exception as exc:
            logger.warning(
                'Semantic index unavailable; applying keyword fallback (%s)',
                type(exc).__name__,
            )
            return self._keyword_fallback(request, mode)
        return self._decorate_search_response(response, requested=mode, applied=mode)

    def _decorate_search_response(self, response, *, requested, applied, warning=''):
        if isinstance(response.data, dict):
            if response.data.get('search_warning'):
                return response
            response.data['search_mode_requested'] = requested
            response.data['search_mode_applied'] = applied
            response.data['search_warning'] = warning
        return response

    def _keyword_fallback(self, request, requested):
        response = super().list(request, *[], **{})
        return self._decorate_search_response(
            response,
            requested=requested,
            applied='keyword',
            warning='semantic_index_unavailable',
        )

    def _semantic_search(self, request, query):
        from .services.vector_store import VectorStoreService
        from .services.embedding import EmbeddingService
        from .services.search_index_control import index_version_is_current

        if not index_version_is_current():
            return self._keyword_fallback(request, 'semantic')

        # The Docker web process intentionally skips eager model loading. Accessing
        # the model here loads it once on the first semantic request; the model lock
        # also joins an in-progress background preload in non-Docker deployments.
        if not EmbeddingService.is_loaded():
            EmbeddingService().model

        vs = VectorStoreService()
        if vs.count() == 0:
            return self._keyword_fallback(request, 'semantic')

        order_by = request.query_params.get('order_by', 'relevance').strip()

        page_size, page = self.search_pagination(request)
        offset = (page - 1) * page_size

        # Fetch enough results to cover any requested page (cap at 1000)
        fetch_n = min(1000, max(200, page_size * 50))

        results = vs.search(query, n=fetch_n)
        if not results:
            return self._empty_response(request)

        news_ids = [r[0] for r in results]

        allowed = set(self.visible_queryset().filter(id__in=news_ids).values_list('id', flat=True))
        news_ids = list(dict.fromkeys(nid for nid in news_ids if nid in allowed))

        # Re-order by time if requested
        if order_by == 'time' and news_ids:
            news_ids = list(News.objects.filter(id__in=news_ids).order_by('-publish_time').values_list('id', flat=True))

        # Count the filtered candidate pool, bounded by the existing vector cap.
        total = len(news_ids)
        page_ids = news_ids[offset:offset + page_size]

        news_map = self.visible_queryset().in_bulk(page_ids)

        ordered = [news_map[nid] for nid in page_ids if nid in news_map]

        serializer = self.get_serializer(ordered, many=True)
        return Response({
            'count': total,
            'next': self._next_url(request, page, total),
            'previous': self._prev_url(request, page),
            'results': serializer.data,
        })

    def _hybrid_search(self, request, query):
        from .services.vector_store import VectorStoreService
        from .services.search_index_control import index_version_is_current

        if not index_version_is_current():
            return self._keyword_fallback(request, 'hybrid')

        order_by = request.query_params.get('order_by', 'relevance').strip()

        # Apply pre-search filters to base queryset
        base_qs = self.visible_queryset()

        # When ordering by time, fetch more results for a better time-ordered pool
        if order_by == 'time':
            keyword_limit = 300
            semantic_n = 500
        else:
            keyword_limit = 100
            semantic_n = 300

        # Keyword search
        keyword_ids = list(filters.SearchFilter().filter_queryset(request, base_qs, self).order_by('-publish_time').values_list('id', flat=True)[:keyword_limit])

        # Semantic search
        vs = VectorStoreService()
        semantic_ids = []
        if vs.count() > 0:
            results = vs.search(query, n=semantic_n)
            vs_ids = [r[0] for r in results]
            allowed = set(base_qs.filter(id__in=vs_ids).values_list('id', flat=True))
            semantic_ids = list(dict.fromkeys(nid for nid in vs_ids if nid in allowed))
        else:
            return self._keyword_fallback(request, 'hybrid')

        # RRF fusion
        fused_ids = reciprocal_rank_fusion(keyword_ids, semantic_ids)

        if not fused_ids:
            return self._empty_response(request)

        # Re-order by time if requested (before category/source filter)
        if order_by == 'time':
            time_ordered = News.objects.filter(id__in=fused_ids).order_by('-publish_time').values_list('id', flat=True)
            fused_ids = list(time_ordered)

        total = len(fused_ids)
        page_size, page = self.search_pagination(request)
        offset = (page - 1) * page_size
        page_ids = fused_ids[offset:offset + page_size]

        news_map = self.visible_queryset().in_bulk(page_ids)

        ordered = [news_map[nid] for nid in page_ids if nid in news_map]

        serializer = self.get_serializer(ordered, many=True)
        return Response({
            'count': total,
            'next': self._next_url(request, page, total),
            'previous': self._prev_url(request, page),
            'results': serializer.data,
        })

    def search_pagination(self, request):
        from rest_framework.exceptions import NotFound
        page_size = self.paginator.get_page_size(request)
        try:
            page = int(request.query_params.get('page', 1))
            if page < 1: raise ValueError
        except (ValueError, TypeError):
            raise NotFound('Invalid page.')
        return page_size, page

    def _empty_response(self, request):
        return Response({
            'count': 0,
            'next': None,
            'previous': None,
            'results': [],
        })

    def _next_url(self, request, page, total):
        page_size = self.paginator.get_page_size(request)
        if page * page_size >= total:
            return None
        params = request.query_params.copy()
        params['page'] = page + 1
        return request.build_absolute_uri(
            request.path + '?' + params.urlencode()
        )

    def _prev_url(self, request, page):
        if page <= 1:
            return None
        params = request.query_params.copy()
        params['page'] = page - 1
        return request.build_absolute_uri(
            request.path + '?' + params.urlencode()
        )


class ProviderComparisonListCreateView(generics.ListCreateAPIView):
    queryset = ProviderComparison.objects.select_related('news', 'news__source').all()
    serializer_class = ProviderComparisonSerializer
    pagination_class = StandardPagination
    permission_classes = [IsActiveSuperuser]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'provider', 'ok', 'quality_score', 'elapsed_ms']
    ordering = ['-created_at']

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        from api.services.article_fetcher.comparison import adapted_sites, comparison_metrics
        response.data['adapted_sites'] = adapted_sites()
        response.data['metrics'] = comparison_metrics(self.filter_queryset(self.get_queryset()))
        return response

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        run_serializer = ProviderComparisonRunSerializer(data=request.data)
        run_serializer.is_valid(raise_exception=True)
        data = run_serializer.validated_data

        from api.services.article_fetcher.comparison import compare_providers, validate_comparison_url
        try:
            if data.get('url'):
                validate_comparison_url(data['url'])
            run_id, comparisons = compare_providers(
                news_id=data.get('news_id'),
                url=data.get('url'),
                expected_title=data.get('expected_title'),
                summary=data.get('summary'),
                provider_names=data.get('providers'),
            )
        except News.DoesNotExist:
            return Response({'news_id': 'News not found'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        result_serializer = self.get_serializer(comparisons, many=True)
        return Response(
            {'run_id': run_id, 'count': len(comparisons), 'results': result_serializer.data},
            status=status.HTTP_201_CREATED,
        )


class ProviderComparisonDetailView(generics.RetrieveAPIView):
    queryset = ProviderComparison.objects.select_related('news', 'news__source').all()
    serializer_class = ProviderComparisonSerializer
    permission_classes = [IsActiveSuperuser]


class ProviderComparisonRetestView(generics.GenericAPIView):
    queryset = ProviderComparison.objects.select_related('news').all()
    serializer_class = ProviderComparisonSerializer
    permission_classes = [IsActiveSuperuser]

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        comparison = self.get_object()
        from api.services.article_fetcher.comparison import retest_comparison
        run_id, comparisons = retest_comparison(comparison)
        serializer = self.get_serializer(comparisons, many=True)
        return Response(
            {'run_id': run_id, 'count': len(comparisons), 'results': serializer.data},
            status=status.HTTP_201_CREATED,
        )


class NewsDetailView(generics.RetrieveAPIView):
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    serializer_class = NewsDetailSerializer


class NewsFetchFullView(generics.GenericAPIView):
    """Read cached content or persist one shared refresh intent."""
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    serializer_class = NewsDetailSerializer
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_protect)
    def post(self, request, pk):
        import math
        from django.utils import timezone
        news = self.get_object()
        force = request.data.get('force') is True
        from api.services.body_access import can_view_article_body
        privileged = can_view_article_body(request.user)
        if has_full_content(news, privileged=privileged) and not force:
            return Response(self.get_serializer(news).data)
        rejection = fetch_eligibility(news, privileged=privileged)
        if rejection or news.full_content_fetch_status == 'blocked' or (news.full_content_fetch_status == 'unsupported' and not privileged):
            data = dict(self.get_serializer(news).data)
            data.update(error_code=rejection or news.full_content_error_code or 'unsupported',
                        error='该文章身份或来源策略暂不支持正文获取。')
            return Response(data, status=422)
        if privileged:
            News.objects.filter(pk=news.pk, url=news.url, full_content_revision=news.full_content_revision).update(full_content_requested_by=request.user)
            news.refresh_from_db()
        outcome = request_full_content(news, force=force, priority=10 if force else 0)
        news.refresh_from_db()
        data = dict(self.get_serializer(news).data)
        if outcome == 'unavailable':
            data.update(error_code='full_content_worker_unavailable', error='正文获取服务暂不可用，请稍后重试。')
            return Response(data, status=503)
        if outcome == 'rejected':
            data.update(error_code='retry_exhausted' if news.full_content_retry_count >= 5 else news.full_content_error_code or 'unsupported', error='该文章暂不支持正文获取。')
            return Response(data, status=422)
        if outcome == 'cached':
            return Response(data)
        response = Response(data, status=202)
        response['Location'] = request.build_absolute_uri(f'/api/news/{news.pk}/')
        wait = (news.full_content_next_attempt_at - timezone.now()).total_seconds() if news.full_content_next_attempt_at else 2
        response['Retry-After'] = str(max(2, math.ceil(wait)))
        return response


class NewsTranslateFullView(generics.GenericAPIView):
    """Translate full article content to Chinese using SSE streaming."""
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    serializer_class = NewsDetailSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Translate full article content to Chinese using SSE streaming."""
        from django.http import StreamingHttpResponse
        import json as json_lib
        from api.translation_sse import translation_sse_records
        # _call_llm_stream is invoked inside the translation_jobs worker, not here.

        news = self.get_object()
        if not has_full_content(news):
            from api.services import shared_translations
            return shared_translations.error_response('请先获取完整原文。', error_code='full_content_not_ready')

        force = request.data.get('force', False)

        # A personally configured API key takes precedence over a subscription.
        from api.services.provider_credentials import has_personal_credential
        from api.services.chatgpt_subscription import active_connection_for_user
        personal_configured = has_personal_credential(request.user)
        if not personal_configured and active_connection_for_user(request.user) is not None:
            from api.subscription_views import subscription_translation_response
            return subscription_translation_response(request, news, force=force)

        from api.services import shared_translations
        shared = shared_translations.get_shared_translation(news)
        if shared is not None:
            # A public-provider request must not silently replace everybody's copy.
            return shared_translations.completed_response(shared)
        if shared_translations.task_is_running(news):
            return shared_translations.waiting_response(news)

        # If a background worker is still running, ALWAYS prefer attaching
        # to it over the snapshot path — this is the cross-device / re-entry
        # live-attach case. Falls through to the job logic below.
        from api.services.translation_jobs import get_job as _get_job
        active_job = _get_job(news.pk)
        worker_in_flight = bool(active_job and not active_job.done)

        # If already translated AND no worker running, stream existing result.
        if news.full_content_zh and not force and not worker_in_flight:
            def existing_stream():
                yield from translation_sse_records({
                    'full_content_zh': news.full_content_zh,
                    'full_content_zh_fetched_at': news.full_content_zh_fetched_at.isoformat() if news.full_content_zh_fetched_at else None
                })
            return StreamingHttpResponse(existing_stream(), content_type='text/event-stream')

        if not news.full_content and not worker_in_flight:
            def error_stream():
                yield f"data: {json_lib.dumps({'error': '请先获取完整原文'})}\n\n"
            return StreamingHttpResponse(error_stream(), content_type='text/event-stream')

        # Check for existing translated link first — but skip when a worker
        # is already running (we'd just be doing duplicate network work).
        if not worker_in_flight:
            from api.services.llm_translator import find_chinese_translation_link, fetch_and_verify_chinese_content
            zh_link = find_chinese_translation_link(news.full_content, news.url)
            if zh_link:
                zh_content = fetch_and_verify_chinese_content(zh_link)
                if zh_content:
                    try:
                        record = shared_translations.publish_translation(
                            news_id=news.pk, digest=shared_translations.source_hash(news.full_content),
                            text=zh_content, provider='source-link',
                        )
                    except shared_translations.SharedTranslationError as exc:
                        return shared_translations.error_response(str(exc))
                    return shared_translations.completed_response(record)

        # Keep the SSE error shape expected by the frontend, but make missing
        # provider configuration actionable instead of persisting a fallback
        # sentence as if it were translated content.
        provider_clients = []
        if not worker_in_flight:
            try:
                if personal_configured:
                    from api.services.provider_credentials import personal_clients_for_user
                    provider_clients = personal_clients_for_user(request.user)
                else:
                    provider_clients = get_clients()
            except Exception as exc:
                from api.services.provider_credentials import ProviderCredentialError
                if not isinstance(exc, ProviderCredentialError):
                    raise
                credential_error = str(exc)

                def credential_error_stream():
                    yield f"data: {json_lib.dumps({'error': credential_error}, ensure_ascii=False)}\n\n"
                return StreamingHttpResponse(credential_error_stream(), content_type='text/event-stream')

        if not worker_in_flight and not provider_clients:
            def provider_error_stream():
                message = (
                    '未配置全文翻译模型提供方：请前往「设置」选择厂商、模型并配置自己的 API Key。'
                )
                yield f"data: {json_lib.dumps({'error': message}, ensure_ascii=False)}\n\n"
            return StreamingHttpResponse(provider_error_stream(), content_type='text/event-stream')

        shared_lease = None
        if not worker_in_flight:
            shared_lease = shared_translations.claim_task(news)
            if shared_lease is None:
                return shared_translations.waiting_response(news)

        # Use the fetched full content for translation.
        context = news.full_content

        from api.services.llm_translator import build_translation_prompt
        prompt = build_translation_prompt(context)

        # ---- Decouple LLM work from HTTP lifecycle --------------------------
        # The actual streaming runs in a background thread (TranslationJob)
        # so refreshing/closing the page does NOT kill the translation.
        # This HTTP generator just polls the job and forwards progress.
        from api.services.translation_jobs import start_or_get_job
        news_pk = news.pk
        source_digest = shared_translations.source_hash(news.full_content)

        def persist_progress(text, is_final):
            """Only whole results enter public storage; partial text stays in RAM."""
            if is_final:
                shared_translations.publish_translation(
                    news_id=news_pk, digest=source_digest, text=text,
                    provider='llm', lease=shared_lease,
                )

        job = start_or_get_job(
            news_pk, prompt, persist_progress,
            shared_lease=shared_lease, clients=provider_clients,
        )

        def translate_stream():
            sent_len = 0
            # If we attached to an in-progress job that already has output,
            # flush what we have immediately.
            if job.text:
                initial = job.text
                yield from translation_sse_records({'progress': initial})
                sent_len = len(initial)

            # Poll-stream loop. Even if the client disconnects here, the
            # worker thread keeps consuming the LLM stream and saving to DB.
            while True:
                try:
                    new_len = job.wait_for_update(sent_len, timeout=1.0)
                    if new_len > sent_len:
                        latest = job.text
                        if len(latest) > sent_len:
                            yield from translation_sse_records({'progress_delta': latest[sent_len:]})
                            sent_len = len(latest)
                    if job.done:
                        break
                except Exception:
                    # Client likely disconnected — leave the worker running.
                    return

            if job.error:
                try:
                    yield f"data: {json_lib.dumps({'error': job.error})}\n\n"
                except Exception:
                    pass
                return

            # The public table is authoritative for completed new jobs.
            try:
                fresh = News.objects.get(pk=news_pk)
                record = shared_translations.get_shared_translation(fresh)
                final_payload = shared_translations.result_payload(record) if record else {
                    'full_content_zh': job.text, 'full_content_zh_fetched_at': None,
                }
            except Exception:
                final_payload = {
                    'full_content_zh': job.text,
                    'full_content_zh_fetched_at': None,
                }

            try:
                yield from translation_sse_records(final_payload, event='complete')
            except Exception:
                pass

        return StreamingHttpResponse(translate_stream(), content_type='text/event-stream')


class NewsChatView(generics.GenericAPIView):
    """Chat with the AI assistant about a news article for the authenticated user."""
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Return chat history."""
        news = self.get_object()
        session = ChatSession.objects.filter(user=request.user, news=news).first()
        return Response({'messages': session.messages if session else []})

    def delete(self, request, pk):
        """Clear chat history."""
        news = self.get_object()
        try:
            clear_chat_history(user_id=request.user.pk, news_id=news.pk)
        except ChatConflict:
            return Response(
                {'error_code': 'chat_conflict', 'error': '聊天记录正在更新，请重试'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({'status': 'cleared'})

    def post(self, request, pk):
        from django.http import StreamingHttpResponse

        news = self.get_object()

        payload = request.data
        user_question = payload.get('question') if hasattr(payload, 'get') else None
        if not isinstance(user_question, str):
            return Response(
                {'error_code': 'invalid_question', 'error': '问题必须是非空文本'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(user_question) > 8000:
            return Response(
                {'error_code': 'question_too_long', 'error': '问题不能超过8000个字符'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_question = user_question.strip()
        if not user_question:
            return Response(
                {'error_code': 'invalid_question', 'error': '问题必须是非空文本'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from api.services.chatgpt_subscription import active_connection_for_user, stream_chat_response
        from api.services.provider_credentials import ProviderCredentialError, personal_clients_for_user
        try:
            personal_clients = personal_clients_for_user(request.user)
        except ProviderCredentialError as exc:
            return Response(
                {'error_code': 'provider_credential_unavailable', 'error': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        subscription_connection = None if personal_clients else active_connection_for_user(request.user)
        provider_clients = personal_clients
        if not provider_clients and subscription_connection is None:
            provider_clients = get_clients()
        if not provider_clients and subscription_connection is None:
            return Response(
                {
                    'error_code': 'provider_credential_required',
                    'error': '请先前往「设置」配置自己的模型 API Key。',
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Request shared durable work; this HTTP request uses current context.
        ensure_full_content(news)
        context = pick_chat_context(news)
        chat_scope = context_scope(news)
        if len(context) > 10000:
            context = context[:10000]
            chat_scope = 'excerpt'

        web_search = request.data.get('web_search', False)

        # Web search via research agent's tool — inject results into context
        # AND pass them to the frontend as structured metadata
        web_sources = []
        web_context = ''
        if web_search:
            try:
                from api.services.research.tools import _tool_search_web, _extract_search_query

                # Extract optimized search keywords from the user question
                primary_query, secondary_query = _extract_search_query(user_question)

                # Run multiple searches for better coverage
                all_results = []
                seen_urls = set()
                for query in [primary_query, secondary_query]:
                    if not query:
                        continue
                    sr = _tool_search_web(query, count=5)
                    for r in sr.get('results', []):
                        url = r.get('url', '')
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append(r)

                if all_results:
                    web_sources = [
                        {
                            'title': r['title'],
                            'url': r.get('url', ''),
                            'snippet': r.get('snippet', '')[:200],
                            'source': r.get('source', ''),
                        }
                        for r in all_results[:8]
                    ]
                    lines = []
                    for i, r in enumerate(web_sources, 1):
                        lines.append(
                            f"{i}. **{r['title']}** ({r.get('source', '')})\n"
                            f"   {r['snippet']}\n"
                            f"   链接: {r.get('url', '')}"
                        )
                    web_context = (
                        "\n## 网络搜索结果 (实时搜索):\n"
                        + "\n\n".join(lines) + "\n"
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Web search failed for chat")

        try:
            chat_snapshot = append_user_message(
                user_id=request.user.pk,
                news_id=news.pk,
                content=user_question,
            )
        except ChatConflict:
            return Response(
                {'error_code': 'chat_conflict', 'error': '聊天记录正在更新，请重试'},
                status=status.HTTP_409_CONFLICT,
            )

        # Build messages for LLM
        system_content = (
            f'你是一位专业的新闻助手。用户正在阅读一篇新闻文章，请基于以下文章内容回答用户的问题。\n\n'
            f'## 可用内容范围: {chat_scope}（summary 仅摘要，excerpt 为节选）\n'
            f'## 文章内容:\n{context}'
        )

        # Inject web search results if available
        if web_context:
            system_content += (
                f'\n\n{web_context}'
                f'\n\n## 回答指引:\n'
                f'以上网络搜索结果来自实时搜索，可能与文章内容有所补充。\n'
                f'请综合文章内容和网络搜索结果回答用户问题，并注明信息来源。\n'
            )

        system_content += (
            f'\n\n## 要求:\n'
            f'1. 必须严格基于文章内容回答，不要编造信息。\n'
            f'2. 如果文章中找不到答案，请明确告知用户。\n'
            f'3. 回答要简洁、清晰、有逻辑。\n'
            f'4. 使用 Markdown 格式，支持列表、加粗等。'
        )

        messages = [
            {
                'role': 'system',
                'content': system_content,
            }
        ]
        
        for msg in chat_snapshot.messages[-20:]:
            messages.append(msg)

        def generate():
            full_response = []
            try:
                import json as _json
                context_metadata = _json.dumps({'type': 'article_context', 'context_scope': chat_scope,
                    'full_content_state': news.full_content_state}, ensure_ascii=False)
                yield f"​__META__{context_metadata}__META__\n\n"
                # Prepend web search sources as structured JSON for frontend display
                if web_sources:
                    import json as _json
                    meta = _json.dumps({'type': 'web_search', 'sources': web_sources}, ensure_ascii=False)
                    yield f"​__META__{meta}__META__\n\n"

                # A signed-in user's active ChatGPT subscription takes precedence.
                # Users without one keep the existing configured-provider path.
                chunks = (
                    stream_chat_response(subscription_connection, messages)
                    if subscription_connection is not None
                    else stream_chat(
                        messages, max_tokens=16000, temperature=0.7,
                        clients=provider_clients,
                    )
                )
                for chunk in chunks:
                    full_response.append(chunk)
                    yield chunk
            except Exception:
                fallback = (
                    "抱歉，ChatGPT 订阅暂时不可用，请在订阅设置中刷新状态或重新连接。"
                    if subscription_connection is not None
                    else "抱歉，AI 服务暂时不可用，请稍后再试。"
                )
                yield f"\n\n[{fallback}]"
                if not full_response:
                    full_response = [fallback]
            finally:
                try:
                    append_assistant_message(
                        user_id=request.user.pk,
                        news_id=news.pk,
                        session_id=chat_snapshot.session_id,
                        generation=chat_snapshot.generation,
                        content=''.join(full_response),
                    )
                except ChatConflict:
                    logger.info('Discarded late chat response for cleared or deleted history')

        response = StreamingHttpResponse(generate(), content_type='text/event-stream')
        if web_search:
            response['X-Web-Search-Used'] = 'true'
        return response


class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.annotate(news_count=Count('news'))


class SourceListView(generics.ListAPIView):
    serializer_class = SourceSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Source.objects.annotate(news_count=Count('news'))
        region = self.request.query_params.get('region')
        if region:
            if region not in {'domestic', 'international'}:
                raise ApiValidationError({'region': '无效的频道地区。'})
            qs = qs.filter(region=region)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        from api.models import NewsSourceItem
        counts = {}
        own_counts = {}
        for row in NewsSourceItem.objects.values('source_key', 'news__source_id').annotate(n=Count('news_id', distinct=True)):
            counts[row['source_key']] = counts.get(row['source_key'], 0) + row['n']
            own_counts[(row['source_key'], row['news__source_id'])] = row['n']
        context.update(channel_counts=counts, own_channel_counts=own_counts)
        return context


class NewsSuggestedQuestionsView(generics.GenericAPIView):
    """Return 3 LLM-generated suggested questions for this article.

    Strategy:
      1. If `news.suggested_questions` is already populated → return cached.
      2. Else call the chat LLM with a tight JSON-only prompt, parse the
         result, persist on the News row, then return.
      3. On ANY error (LLM unreachable, JSON parse fail, empty list) → fall
         back to the hardcoded 3-question list so the chat panel always shows
         3 chips. Endpoint always returns 200 unless the article is missing.

    Reuses the same chat LLM client (kimi-k2.5 via Volcengine/DashScope) used
    by NewsChatView, so there's no new API key or model to configure.
    """
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        import json
        from django.utils import timezone

        news = self.get_object()

        # ?force=1 from frontend "换一批" button — skip cache, force fresh LLM call.
        # On failure we keep the old cache (see except branch), so this is safe.
        force = request.query_params.get('force') in ('1', 'true', 'True')

        # Cache hit (unless forced)
        if not force and news.suggested_questions and len(news.suggested_questions) >= 3:
            return Response({'questions': news.suggested_questions[:3], 'context_scope': context_scope(news)})

        # Auto-fetch full article so suggestions are based on the real body,
        # not the short list-preview blurb. No-op if already cached.
        ensure_full_content(news)
        expected_content_revision = news.full_content_revision
        suggestion_scope = context_scope(news)

        # Build context (same chain as chat view)
        context = pick_chat_context(news)
        if len(context) > 6000:
            context = context[:6000]
        title = news.title_zh or news.title

        prompt = (
            f'你是一个新闻阅读助手。请阅读下面这篇文章，然后生成 3 个用户读完后'
            f'最可能想问的问题。要求：\n'
            f'1. 每个问题必须基于本文实际内容，不要泛泛而谈\n'
            f'2. 问题要简短自然，像一个真人读者会问的\n'
            f'3. 三个问题角度不同（一个事实/一个分析/一个拓展）\n'
            f'4. 只输出一个 JSON 数组，形如 ["问题1", "问题2", "问题3"]，'
            f'不要有任何解释、Markdown 或其它文字。\n\n'
            f'## 标题\n{title}\n\n'
            f'## 可用内容范围: {suggestion_scope}\n{context}'
        )

        try:
            from api.services.chatgpt_subscription import active_connection_for_user, stream_chat_response

            from api.services.provider_credentials import personal_clients_for_user
            personal_clients = personal_clients_for_user(request.user)
            connection = None if personal_clients else active_connection_for_user(request.user)
            if personal_clients:
                client, model = personal_clients[0]
                completion = client.chat.completions.create(
                    model=model,
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.6,
                )
                raw = completion.choices[0].message.content or ''
            elif connection is not None:
                raw = ''.join(stream_chat_response(
                    connection,
                    [{'role': 'user', 'content': prompt}],
                ))
            else:
                clients = get_clients()
                if not clients:
                    raise ValueError("未配置翻译服务 API Key")
                client, model = clients[0]
                completion = client.chat.completions.create(
                    model=model,
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.6,
                )
                raw = completion.choices[0].message.content or ''
            # Strip optional markdown code fence
            raw = raw.strip()
            if raw.startswith('```'):
                raw = raw.strip('`')
                # Drop leading "json\n" if present
                if raw.lower().startswith('json'):
                    raw = raw[4:].lstrip()
            questions = json.loads(raw)
            if not isinstance(questions, list) or len(questions) < 3:
                raise ValueError('LLM response did not yield 3 questions')
            questions = [str(q).strip() for q in questions[:3] if str(q).strip()]
            if len(questions) < 3:
                raise ValueError('fewer than 3 non-empty questions')

            from api.services.full_content_status import save_suggested_questions
            save_suggested_questions(news, questions, expected_revision=expected_content_revision)
            return Response({'questions': questions, 'context_scope': suggestion_scope})
        except Exception as e:
            # Fall back silently — UX should never show "loading questions failed"
            import logging
            logging.getLogger(__name__).warning(
                'suggested-questions LLM failed (%s)', type(e).__name__,
            )
            return Response({'questions': SUGGESTED_QUESTIONS_FALLBACK, 'context_scope': suggestion_scope})


# ─── Favorite / Like / Bookmark API ─────────────────────────────────────

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .serializers import FavoriteSerializer
from .models import Favorite


class FavoriteListView(generics.ListCreateAPIView):
    """
    GET  /api/favorites/           — list authenticated user's favorites
    POST /api/favorites/           — like or bookmark a news article

    POST body: { "news_id": 123, "type": "like" | "bookmark" }
    If the same user + news + type already exists, it is removed (toggle).
    """
    serializer_class = FavoriteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Favorite.objects.filter(user=self.request.user).select_related(
            'news', 'news__source', 'news__category',
        )
        fav_type = self.request.query_params.get('type')
        if fav_type in ('like', 'bookmark'):
            qs = qs.filter(type=fav_type)
        return qs

    def create(self, request, *args, **kwargs):
        news_id = request.data.get('news_id')
        fav_type = request.data.get('type')

        if fav_type not in ('like', 'bookmark'):
            return Response(
                {'error': 'type must be "like" or "bookmark"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if already exists → toggle (remove)
        existing = Favorite.objects.filter(
            user=request.user, news_id=news_id, type=fav_type,
        ).first()

        if existing:
            pk = existing.pk
            news_data = {
                'id': existing.news_id,
                'title': existing.news.title,
                'title_zh': existing.news.title_zh or '',
                'url': existing.news.url,
                'cover_image': existing.news.cover_image or '',
                'source': {'name': existing.news.source.name},
                'category': {'name': existing.news.category.name},
                'publish_time': existing.news.publish_time,
            }
            existing.delete()
            return Response({
                'id': pk,
                'news': news_data,
                'type': fav_type,
                'created_at': existing.created_at.isoformat() if hasattr(existing.created_at, 'isoformat') else str(existing.created_at),
                'removed': True,
            }, status=status.HTTP_200_OK)

        # Create new favorite
        serializer = self.get_serializer(data={**request.data})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FavoriteDestroyView(generics.DestroyAPIView):
    """DELETE /api/favorites/<pk>/ — remove a favorite."""
    queryset = Favorite.objects.all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Favorite.objects.filter(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavoriteCheckView(generics.GenericAPIView):
    """
    GET /api/favorites/check/?news_id=123
    Returns like/bookmark status and counts for the given news article.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        news_id = request.query_params.get('news_id')
        if not news_id:
            return Response(
                {'error': 'news_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_favs = Favorite.objects.filter(
            user=request.user, news_id=news_id,
        )
        is_liked = user_favs.filter(type='like').exists()
        is_bookmarked = user_favs.filter(type='bookmark').exists()

        # Global counts (all users)
        like_count = Favorite.objects.filter(news_id=news_id, type='like').count()
        bookmark_count = Favorite.objects.filter(news_id=news_id, type='bookmark').count()

        return Response({
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'like_count': like_count,
            'bookmark_count': bookmark_count,
        })


# ─── Blocked News API ──────────────────────────────────────────────────

class BlockedNewsListView(generics.ListCreateAPIView):
    """
    GET    /api/blocked/   — list authenticated user's blocked news
    POST   /api/blocked/   — block a news article (idempotent)
    DELETE /api/blocked/   — unblock a news article
    """
    serializer_class = BlockedNewsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return BlockedNews.objects.filter(
            user=self.request.user,
        ).select_related('news', 'news__source', 'news__category')

    def create(self, request, *args, **kwargs):
        news_id = request.data.get('news_id')
        if not news_id:
            return Response(
                {'error': 'news_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not News.objects.filter(pk=news_id).exists():
            return Response(
                {'error': 'News not found'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        block, created = BlockedNews.objects.get_or_create(
            user=request.user,
            news_id=news_id,
        )
        if not created:
            return Response({
                'id': block.pk,
                'news_id': news_id,
                'created': False,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(block)
        data = serializer.data
        data['created'] = True
        return Response(data, status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        """Unblock a news article. Body: { "news_id": 123 }"""
        news_id = request.data.get('news_id')
        if not news_id:
            return Response(
                {'error': 'news_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deleted, _ = BlockedNews.objects.filter(
            user=request.user, news_id=news_id,
        ).delete()
        return Response({'removed': deleted > 0})


class BlockedNewsCheckView(generics.GenericAPIView):
    """GET /api/blocked/check/?news_id=123 — check if news is blocked."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        news_id = request.query_params.get('news_id')
        if not news_id:
            return Response(
                {'error': 'news_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        is_blocked = BlockedNews.objects.filter(
            user=request.user, news_id=news_id,
        ).exists()
        return Response({'is_blocked': is_blocked})


# ─── Authentication API ─────────────────────────────────────────────────

@api_view(['GET', 'HEAD'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
    """GET /api/auth/csrf/ — returns CSRF token for SPA to include in subsequent requests."""
    return Response({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([AnonymousCsrfSessionAuthentication])
@ensure_csrf_cookie
def auth_register(request):
    """POST /api/auth/register/ — create a new user and log them in."""
    try:
        reserve_registration_attempts(request.META.get('REMOTE_ADDR'))
    except InvalidClientAddress:
        return Response(
            {'error_code': 'invalid_client_address', 'error': '客户端地址无效'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except RateLimitExceeded as error:
        return Response(
            {'error_code': 'auth_rate_limited', 'error': '请求过于频繁，请稍后重试'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={'Retry-After': str(error.retry_after)},
        )
    except AuthSecurityBusy:
        return Response(
            {'error_code': 'auth_security_busy', 'error': '认证安全服务暂不可用'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    payload = request.data
    get_value = payload.get if hasattr(payload, 'get') else lambda _key, _default=None: None
    raw_username = get_value('username')
    raw_email = get_value('email')
    password = get_value('password')
    invite_token = get_value('invite_token')
    try:
        if not isinstance(raw_username, str):
            raise ValidationError('invalid username')
        username = User.normalize_username(raw_username.strip())
        if not 1 <= len(username) <= 150:
            raise ValidationError('invalid username')
        username = User._meta.get_field('username').clean(username, None)

        if not isinstance(raw_email, str):
            raise ValidationError('invalid email')
        email = normalize_email(raw_email)
        if not email:
            raise ValidationError('invalid email')
        email = User._meta.get_field('email').clean(email, None)
        EmailValidator()(email)

        if not isinstance(password, str) or len(password) > 1024:
            raise ValidationError('invalid password')
        candidate = User(username=username, email=email)
        from django.contrib.auth.password_validation import validate_password
        validate_password(password, user=candidate)
    except ValidationError:
        return Response(
            {'error_code': 'invalid_registration', 'error': '注册信息无效'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def establish_session(user):
        invalidate_authorization_attempts_for_session(request.session.session_key or '')
        login(request, user)
        # Persist the session inside the same transaction as the invite
        # consumption so a failed session write cannot spend an invitation.
        request.session.save()

    try:
        user = create_registered_user(
            username=username,
            email=email,
            password=password,
            invite_token=invite_token,
            require_invite=settings.DJANGO_ENV == 'production',
            on_created=establish_session,
        )
    except SignupInviteRequired:
        return Response(
            {'error_code': 'invite_required', 'error': '需要有效且匹配邮箱的一次性邀请'},
            status=status.HTTP_403_FORBIDDEN,
        )
    except RegistrationUnavailable:
        return Response(
            {'error_code': 'registration_unavailable', 'error': '暂时无法使用该注册信息'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except AuthSecurityBusy:
        return Response(
            {'error_code': 'auth_security_busy', 'error': '认证安全服务暂不可用'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response({
        'id': user.pk,
        'username': user.username,
        'is_superuser': user.is_superuser,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([AnonymousCsrfSessionAuthentication])
@ensure_csrf_cookie
def auth_login(request):
    """POST /api/auth/login/ — authenticate and create a session."""
    payload = request.data
    get_value = payload.get if hasattr(payload, 'get') else lambda _key, _default=None: None
    raw_username = get_value('username')
    raw_password = get_value('password')
    username = raw_username.strip() if isinstance(raw_username, str) else ''
    password = raw_password if isinstance(raw_password, str) else ''

    try:
        reserve_login_attempts(request.META.get('REMOTE_ADDR'), username)
    except InvalidClientAddress:
        return Response(
            {'error_code': 'invalid_client_address', 'error': '客户端地址无效'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except RateLimitExceeded as error:
        return Response(
            {'error_code': 'auth_rate_limited', 'error': '请求过于频繁，请稍后重试'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={'Retry-After': str(error.retry_after)},
        )
    except AuthSecurityBusy:
        return Response(
            {'error_code': 'auth_security_busy', 'error': '认证安全服务暂不可用'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'error': '用户名或密码错误'}, status=status.HTTP_401_UNAUTHORIZED)

    invalidate_authorization_attempts_for_session(request.session.session_key or '')
    login(request, user)
    return Response({
        'id': user.pk,
        'username': user.username,
        'is_superuser': user.is_superuser,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([SessionAuthentication])
def auth_logout(request):
    """POST /api/auth/logout/ — end the current session."""
    invalidate_authorization_attempts_for_session(request.session.session_key or '')
    logout(request)
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_me(request):
    """GET /api/auth/me/ — return current user info."""
    return Response({
        'id': request.user.pk,
        'username': request.user.username,
        'is_superuser': request.user.is_superuser,
    })


# ─── TTS (Text-to-Speech) API ──────────────────────────────────────────

class NewsTTSView(generics.GenericAPIView):
    """Stream TTS audio for a news article using Edge TTS (Microsoft Natural voices).

    GET /api/news/<pk>/tts/?language=zh&voice=yunyang&scope=full

    scope: 'summary' (title + short blurb) or 'full' (title + full article).
    Returns audio/mpeg stream. Supports caching — repeat requests serve from cache.
    """
    queryset = News.objects.select_related('source', 'category').prefetch_related('source_items').all()
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import asyncio
        import logging
        from django.http import StreamingHttpResponse, FileResponse
        from api.services.tts_service import (
            TTSContentUnavailable, build_cache_variant, clean_for_tts,
            configure_edge_tts_endpoint,
            get_cached_audio, pick_tts_voice, resolve_tts_content, save_to_cache,
        )

        news = self.get_object()

        # Resolve parameters
        language = request.query_params.get('language')
        if language is None:
            # Backwards compatibility for clients created before speech language
            # was separated from the page display mode.
            language = 'original' if request.query_params.get('displayMode') == 'original' else 'zh'
        voice_pref = request.query_params.get('voice', '')
        scope = request.query_params.get('scope', 'full')

        try:
            resolved = resolve_tts_content(news, request.user, language, scope)
        except TTSContentUnavailable as exc:
            response_status = (
                status.HTTP_409_CONFLICT
                if exc.code in {'translation_required', 'source_content_required'}
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({'code': exc.code, 'message': exc.message}, status=response_status)

        voice = pick_tts_voice(
            source_language=news.source.language,
            display_mode=resolved.language,
            has_zh=resolved.language == 'zh',
            voice_pref=voice_pref,
        )

        clean_content = clean_for_tts(resolved.content)
        clean_title = clean_for_tts(resolved.title)
        speech_text = '。'.join(part for part in (clean_title, clean_content) if part)
        if not speech_text.strip():
            return Response(
                {'code': 'source_content_required', 'message': '所选范围暂无可朗读内容。'},
                status=status.HTTP_409_CONFLICT,
            )

        cache_variant = build_cache_variant(resolved, scope, voice, speech_text)
        cached = get_cached_audio(pk, cache_variant)
        if cached:
            response = FileResponse(
                open(cached, 'rb'),
                content_type='audio/mpeg',
                as_attachment=False,
            )
            response['Cache-Control'] = 'private, max-age=86400'
            return response

        try:
            import edge_tts
        except ImportError:
            logging.getLogger(__name__).exception('TTS dependency edge-tts is not installed')
            return Response(
                {'code': 'tts_unavailable', 'message': '语音服务暂不可用。'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        configure_edge_tts_endpoint()

        # Complete the upstream handshake and receive the first audio chunk
        # before returning a streaming response. Otherwise a WebSocket failure
        # occurs after response construction and Waitress can only expose an
        # opaque 500/broken audio stream to the browser.
        audio_chunks = []
        loop = asyncio.new_event_loop()

        async def _gen():
            communicate = edge_tts.Communicate(speech_text, voice)
            async for chunk in communicate.stream():
                if chunk.get('type') == 'audio' and 'data' in chunk:
                    yield chunk['data']

        gen = _gen()
        try:
            first_chunk = loop.run_until_complete(gen.__anext__())
        except Exception as exc:
            try:
                loop.run_until_complete(gen.aclose())
            finally:
                loop.close()
            logging.getLogger(__name__).warning(
                'TTS upstream unavailable endpoint=%s error=%s',
                getattr(settings, 'EDGE_TTS_ENDPOINT', 'default'),
                type(exc).__name__,
            )
            return Response(
                {'code': 'tts_unavailable', 'message': '语音服务暂不可用，请稍后重试。'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        def generate_and_stream():
            completed = False
            try:
                audio_chunks.append(first_chunk)
                yield first_chunk
                while True:
                    try:
                        chunk = loop.run_until_complete(gen.__anext__())
                        audio_chunks.append(chunk)
                        yield chunk
                    except StopAsyncIteration:
                        completed = True
                        break
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    'TTS upstream stream interrupted endpoint=%s error=%s',
                    getattr(settings, 'EDGE_TTS_ENDPOINT', 'default'),
                    type(exc).__name__,
                )
            finally:
                try:
                    loop.run_until_complete(gen.aclose())
                finally:
                    loop.close()
                # Save to cache after generation completes
                if completed and audio_chunks:
                    try:
                        save_to_cache(pk, cache_variant, b''.join(audio_chunks))
                    except Exception:
                        pass  # Cache write failure is non-critical

        response = StreamingHttpResponse(
            generate_and_stream(),
            content_type='audio/mpeg',
        )
        response['Cache-Control'] = 'private, max-age=86400'
        return response
