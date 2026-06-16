from django.db.models import Count, Q
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt, csrf_protect
from rest_framework import generics, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters import rest_framework as django_filters
from .models import Category, Source, News, ChatSession, BlockedNews, ProviderComparison
from .serializers import (
    CategorySerializer, SourceSerializer,
    NewsListSerializer, NewsDetailSerializer,
    BlockedNewsSerializer,
    ProviderComparisonRunSerializer, ProviderComparisonSerializer,
)
# Module-level import so tests can patch `api.views.get_openai_client`
from api.services.llm_translator import get_openai_client, get_clients, stream_chat
from api.services.article_fetcher import FetchError, fetch_article_markdown

# Hardcoded fallback shown when the LLM is unreachable / returns garbage
SUGGESTED_QUESTIONS_FALLBACK = [
    '帮我用一句话总结这篇文章',
    '这篇文章里最重要的三个观点是什么？',
    '有什么背景知识可以帮我更好理解？',
]


def pick_chat_context(news):
    """Pick the best available article body for AI consumption.

    Preference order (richest + Chinese first):
      1. full_content_zh — translated full article (best)
      2. full_content    — original full article (Chinese readers can still parse)
      3. content_zh      — translated list-preview blurb
      4. content         — original list-preview blurb (last resort)

    Returns a non-empty string (empty only if every field is empty).
    """
    return (
        news.full_content_zh
        or news.full_content
        or news.content_zh
        or news.content
        or ''
    )


def ensure_full_content(news):
    """Best-effort: make sure news.full_content is populated before AI sees it.

    No-op if full_content already exists or news has no URL.
    On provider-chain failure, logs a warning and returns silently — caller falls back
    to whatever shorter content is available via pick_chat_context().

    This is what makes "open chat without clicking 'fetch full article' first"
    work end-to-end. The first chat call may pay a 2-10s latency hit for the
    real fetch chain; subsequent calls hit the cached field.
    """
    import logging
    from django.utils.timezone import now as tz_now

    from api.services.full_content_status import classify_fetch_error, mark_failed, mark_success

    if news.full_content:
        return
    if not news.url:
        return

    try:
        result = fetch_article_markdown(
            news.url,
            expected_title=news.title,
            summary=news.content,
        )
        news.full_content = result.markdown
        news.full_content_fetched_at = tz_now()
        news.save(update_fields=['full_content', 'full_content_fetched_at'])
        mark_success(news, result)
    except Exception as e:
        try:
            classified = classify_fetch_error(e)
            mark_failed(news, e, status=classified)
        except Exception:
            pass  # Never let status tracking break ensure_full_content
        logging.getLogger(__name__).warning(
            'ensure_full_content: real fetch failed for news=%s: %s',
            news.pk, e,
        )


class CommaSeparatedIntegerFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class NewsFilter(django_filters.FilterSet):
    category = CommaSeparatedIntegerFilter(field_name='category', lookup_expr='in')
    source = CommaSeparatedIntegerFilter(field_name='source', lookup_expr='in')
    source__source_type = django_filters.CharFilter(field_name='source__source_type')
    full_content = django_filters.BooleanFilter(
        method='filter_full_content',
    )
    publish_time_after = django_filters.IsoDateTimeFilter(
        field_name='publish_time',
        lookup_expr='gte',
    )

    class Meta:
        model = News
        fields = ['category', 'source', 'source__source_type']

    def filter_full_content(self, queryset, name, value):
        if value:
            return queryset.filter(full_content_fetch_status='success')
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
    serializer_class = NewsListSerializer
    pagination_class = StandardPagination
    filter_backends = [django_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = NewsFilter
    search_fields = ['title', 'content', 'title_zh', 'content_zh']
    ordering_fields = ['publish_time', 'created_at']
    ordering = ['-publish_time']

    def get_queryset(self):
        qs = News.objects.select_related('source', 'category')
        # Hide duplicates by default
        if self.request.query_params.get('include_dupes', 'false') != 'true':
            qs = qs.filter(related_to__isnull=True)
        # Exclude blocked news for authenticated users
        if self.request.user.is_authenticated:
            blocked_ids = BlockedNews.objects.filter(
                user=self.request.user,
            ).values_list('news_id', flat=True)
            if blocked_ids:
                qs = qs.exclude(pk__in=blocked_ids)
        return qs

    def list(self, request, *args, **kwargs):
        search_query = request.query_params.get('search', '').strip()
        mode = request.query_params.get('mode', 'keyword').strip()

        if not search_query or mode == 'keyword':
            # Wire `order_by=time` into DRF's ordering param for keyword mode
            order_by = request.query_params.get('order_by', '').strip()
            if order_by == 'time' and 'ordering' not in request.query_params:
                request.query_params = request.query_params.copy()
                request.query_params['ordering'] = '-publish_time'
            return super().list(request, *args, **kwargs)

        if mode == 'semantic':
            return self._semantic_search(request, search_query)

        # mode == 'hybrid'
        return self._hybrid_search(request, search_query)

    def _apply_filters(self, qs, request):
        """Apply new filter params to the base queryset before search."""
        full_content = request.query_params.get('full_content', '').strip()
        if full_content == 'true':
            qs = qs.filter(full_content_fetch_status='success')

        publish_after = request.query_params.get('publish_time_after', '').strip()
        if publish_after:
            from datetime import datetime
            try:
                # Support both '2026-06-01' and ISO format
                dt = datetime.fromisoformat(publish_after.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    from django.utils.timezone import make_aware
                    dt = make_aware(dt)
                qs = qs.filter(publish_time__gte=dt)
            except (ValueError, TypeError):
                pass

        return qs

    def _reorder_results(self, news_ids, order_by):
        """Re-order result IDs if order_by=time, else keep original order."""
        if order_by != 'time' or not news_ids:
            return news_ids

        # Fetch articles ordered by publish_time, preserving relevance subset
        time_ordered = News.objects.filter(id__in=news_ids).order_by('-publish_time').values_list('id', flat=True)
        return list(time_ordered)

    def _semantic_search(self, request, query):
        from .services.vector_store import VectorStoreService
        from .services.embedding import EmbeddingService

        if not EmbeddingService.is_loaded():
            EmbeddingService.wait_until_ready(timeout=120)

        vs = VectorStoreService()
        if vs.count() == 0:
            return super().list(request, *[], **{})

        order_by = request.query_params.get('order_by', 'relevance').strip()

        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        offset = (page - 1) * page_size

        # Fetch enough results to cover any requested page (cap at 1000)
        fetch_n = min(1000, max(200, page_size * 50))

        results = vs.search(query, n=fetch_n)
        if not results:
            return self._empty_response(request)

        news_ids = [r[0] for r in results]

        # Apply filters (full_content, publish_time_after) to the ID list
        if request.query_params.get('full_content') == 'true' or request.query_params.get('publish_time_after'):
            base_qs = self._apply_filters(News.objects.all(), request)
            allowed = set(base_qs.filter(id__in=news_ids).values_list('id', flat=True))
            news_ids = [nid for nid in news_ids if nid in allowed]

        # Re-order by time if requested
        if order_by == 'time' and news_ids:
            news_ids = list(News.objects.filter(id__in=news_ids).order_by('-publish_time').values_list('id', flat=True))

        # Use ORM count() for the true total — the ID list may be capped by fetch_n
        # but the actual DB total reflects how many articles really match.
        total = News.objects.filter(id__in=news_ids).count()
        page_ids = news_ids[offset:offset + page_size]

        if not page_ids:
            return self._empty_response(request)

        news_map = News.objects.select_related(
            'source', 'category'
        ).in_bulk(page_ids)

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

        order_by = request.query_params.get('order_by', 'relevance').strip()

        # Apply pre-search filters to base queryset
        base_qs = self._apply_filters(self.filter_queryset(self.get_queryset()), request)

        # When ordering by time, fetch more results for a better time-ordered pool
        if order_by == 'time':
            keyword_limit = 300
            semantic_n = 500
        else:
            keyword_limit = 100
            semantic_n = 300

        # Keyword search
        keyword_results = base_qs.filter(
            Q(title__icontains=query) | Q(content__icontains=query)
        )[:keyword_limit]
        keyword_ids = [n.id for n in keyword_results]

        # Semantic search
        vs = VectorStoreService()
        semantic_ids = []
        if vs.count() > 0:
            results = vs.search(query, n=semantic_n)
            vs_ids = [r[0] for r in results]
            # Apply filters to the vector store results
            if request.query_params.get('full_content') == 'true' or request.query_params.get('publish_time_after'):
                base_qs_filter = self._apply_filters(News.objects.all(), request)
                allowed = set(base_qs_filter.filter(id__in=vs_ids).values_list('id', flat=True))
                semantic_ids = [nid for nid in vs_ids if nid in allowed]
            else:
                semantic_ids = vs_ids

        # RRF fusion
        fused_ids = reciprocal_rank_fusion(keyword_ids, semantic_ids)

        if not fused_ids:
            return self._empty_response(request)

        # Re-order by time if requested (before category/source filter)
        if order_by == 'time':
            time_ordered = News.objects.filter(id__in=fused_ids).order_by('-publish_time').values_list('id', flat=True)
            fused_ids = list(time_ordered)

        # Apply category/source filters to fused results
        category = request.query_params.get('category')
        source = request.query_params.get('source')
        if category or source:
            filter_qs = News.objects.filter(id__in=fused_ids)
            if category:
                cat_ids = [c.strip() for c in category.split(',')]
                filter_qs = filter_qs.filter(category_id__in=cat_ids)
            if source:
                src_ids = [s.strip() for s in source.split(',')]
                filter_qs = filter_qs.filter(source_id__in=src_ids)
            allowed_ids = set(filter_qs.values_list('id', flat=True))
            fused_ids = [fid for fid in fused_ids if fid in allowed_ids]

        total = News.objects.filter(id__in=fused_ids).count()
        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        offset = (page - 1) * page_size
        page_ids = fused_ids[offset:offset + page_size]

        if not page_ids:
            return self._empty_response(request)

        news_map = News.objects.select_related(
            'source', 'category'
        ).in_bulk(page_ids)

        ordered = [news_map[nid] for nid in page_ids if nid in news_map]

        serializer = self.get_serializer(ordered, many=True)
        return Response({
            'count': total,
            'next': self._next_url(request, page, total),
            'previous': self._prev_url(request, page),
            'results': serializer.data,
        })

    def _empty_response(self, request):
        return Response({
            'count': 0,
            'next': None,
            'previous': None,
            'results': [],
        })

    def _next_url(self, request, page, total):
        page_size = int(request.query_params.get('page_size', 20))
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
    permission_classes = [IsAuthenticated]
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
    permission_classes = [IsAuthenticated]


class ProviderComparisonRetestView(generics.GenericAPIView):
    queryset = ProviderComparison.objects.select_related('news').all()
    serializer_class = ProviderComparisonSerializer
    permission_classes = [IsAuthenticated]

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
    queryset = News.objects.select_related('source', 'category').all()
    serializer_class = NewsDetailSerializer


class NewsFetchFullView(generics.GenericAPIView):
    """Fetch verified real article Markdown and persist to database."""
    queryset = News.objects.select_related('source', 'category').all()
    serializer_class = NewsDetailSerializer
    permission_classes = []  # Public access

    @method_decorator(csrf_exempt)
    def post(self, request, pk):
        from django.utils.timezone import now as tz_now
        import logging

        logger = logging.getLogger(__name__)
        news = self.get_object()

        force = request.data.get('force', False)

        # If already has full content and not forcing, return cached version
        if news.full_content and not force:
            serializer = self.get_serializer(news)
            return Response(serializer.data)

        url = news.url
        if not url:
            return Response(
                {'error': 'No URL available for this article'},
                status=400,
            )

        # Track fetch status
        from api.services.full_content_status import (
            classify_fetch_error,
            mark_failed,
            mark_fetching,
            mark_success,
        )
        mark_fetching(news)

        try:
            result = fetch_article_markdown(
                url,
                expected_title=news.title,
                summary=news.content,
            )

            news.full_content = result.markdown
            news.full_content_fetched_at = tz_now()
            news.save(update_fields=['full_content', 'full_content_fetched_at'])
            mark_success(news, result)

            serializer = self.get_serializer(news)
            return Response(serializer.data)

        except FetchError as e:
            classified = classify_fetch_error(e)
            mark_failed(news, e, status=classified)
            logger.warning('Full-content fetch failed for %s [%s]: %s', url, classified, e)
            news.refresh_from_db()
            return Response(
                {
                    'error': '原文抓取失败，外部站点当前不可达，可稍后重试。',
                    'full_content_fetch_status': news.full_content_fetch_status,
                    'full_content_fetch_error': news.full_content_fetch_error,
                    'full_content_fetch_provider': news.full_content_fetch_provider,
                    'full_content_quality_score': news.full_content_quality_score,
                    'full_content_retry_count': news.full_content_retry_count,
                    'last_full_content_attempt': (
                        news.last_full_content_attempt.isoformat()
                        if news.last_full_content_attempt
                        else None
                    ),
                },
                status=502,
            )
        except Exception as e:
            mark_failed(news, e)
            logger.exception('Unexpected full-content fetch error for %s: %s', url, e)
            news.refresh_from_db()
            return Response(
                {
                    'error': '原文抓取失败，外部站点当前不可达，可稍后重试。',
                    'full_content_fetch_status': news.full_content_fetch_status,
                    'full_content_fetch_error': news.full_content_fetch_error,
                    'full_content_fetch_provider': news.full_content_fetch_provider,
                    'full_content_quality_score': news.full_content_quality_score,
                    'full_content_retry_count': news.full_content_retry_count,
                    'last_full_content_attempt': (
                        news.last_full_content_attempt.isoformat()
                        if news.last_full_content_attempt
                        else None
                    ),
                },
                status=502,
            )


import json as json_lib

class NewsTranslateFullView(generics.GenericAPIView):
    """Translate full article content to Chinese using SSE streaming."""
    queryset = News.objects.select_related('source', 'category').all()
    serializer_class = NewsDetailSerializer
    permission_classes = []

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        """Translate full article content to Chinese using SSE streaming."""
        from django.http import StreamingHttpResponse
        from django.utils import timezone
        import json as json_lib
        # _call_llm_stream is invoked inside the translation_jobs worker, not here.

        news = self.get_object()

        force = request.data.get('force', False)

        # If a background worker is still running, ALWAYS prefer attaching
        # to it over the snapshot path — this is the cross-device / re-entry
        # live-attach case. Falls through to the job logic below.
        from api.services.translation_jobs import get_job as _get_job
        active_job = _get_job(news.pk)
        worker_in_flight = bool(active_job and not active_job.done)

        # If already translated AND no worker running, stream existing result.
        if news.full_content_zh and not force and not worker_in_flight:
            def existing_stream():
                data = json_lib.dumps({
                    'full_content_zh': news.full_content_zh,
                    'full_content_zh_fetched_at': news.full_content_zh_fetched_at.isoformat() if news.full_content_zh_fetched_at else None
                }, ensure_ascii=False)
                yield f"data: {data}\n\n"
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
                    news.full_content_zh = zh_content
                    news.full_content_zh_fetched_at = timezone.now()
                    news.save(update_fields=['full_content_zh', 'full_content_zh_fetched_at'])
                    def cached_stream():
                        yield f"event: complete\ndata: {json_lib.dumps({'full_content_zh': zh_content, 'full_content_zh_fetched_at': news.full_content_zh_fetched_at.isoformat()}, ensure_ascii=False)}\n\n"
                    return StreamingHttpResponse(cached_stream(), content_type='text/event-stream')

        # FIX: Use the fetched full content for translation
        context = news.full_content
        if len(context) > 40000:
            context = context[:40000]

        from api.services.llm_translator import build_translation_prompt
        prompt = build_translation_prompt(context)

        # ---- Decouple LLM work from HTTP lifecycle --------------------------
        # The actual streaming runs in a background thread (TranslationJob)
        # so refreshing/closing the page does NOT kill the translation.
        # This HTTP generator just polls the job and forwards progress.
        from api.services.translation_jobs import start_or_get_job
        news_pk = news.pk

        def persist_progress(text, is_final):
            """Called from worker thread — re-query and save to avoid stale state."""
            try:
                obj = News.objects.get(pk=news_pk)
                obj.full_content_zh = text
                obj.full_content_zh_fetched_at = timezone.now()
                obj.save(update_fields=['full_content_zh', 'full_content_zh_fetched_at'])
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f'persist_progress failed for news={news_pk}: {e}'
                )

        job = start_or_get_job(news_pk, prompt, persist_progress)

        def translate_stream():
            sent_len = 0
            # If we attached to an in-progress job that already has output,
            # flush what we have immediately.
            if job.text:
                data = json_lib.dumps({'progress': job.text}, ensure_ascii=False)
                yield f"data: {data}\n\n"
                sent_len = len(job.text)

            # Poll-stream loop. Even if the client disconnects here, the
            # worker thread keeps consuming the LLM stream and saving to DB.
            while True:
                try:
                    new_len = job.wait_for_update(sent_len, timeout=1.0)
                    if new_len > sent_len:
                        data = json_lib.dumps({'progress': job.text}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                        sent_len = new_len
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

            # Re-read to pick up the fetched_at timestamp we just saved.
            try:
                fresh = News.objects.get(pk=news_pk)
                final_payload = {
                    'full_content_zh': fresh.full_content_zh or job.text,
                    'full_content_zh_fetched_at': (
                        fresh.full_content_zh_fetched_at.isoformat()
                        if fresh.full_content_zh_fetched_at else None
                    ),
                }
            except Exception:
                final_payload = {
                    'full_content_zh': job.text,
                    'full_content_zh_fetched_at': None,
                }

            try:
                yield (
                    "event: complete\n"
                    f"data: {json_lib.dumps(final_payload, ensure_ascii=False)}\n\n"
                )
            except Exception:
                pass

        return StreamingHttpResponse(translate_stream(), content_type='text/event-stream')


class NewsChatView(generics.GenericAPIView):
    """Chat with the AI assistant about a specific news article. Supports persistence."""
    queryset = News.objects.select_related('source', 'category').all()
    permission_classes = []

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, pk):
        """Return chat history."""
        news = self.get_object()
        try:
            session = ChatSession.objects.get(news=news)
            return Response({'messages': session.messages})
        except ChatSession.DoesNotExist:
            return Response({'messages': []})

    def delete(self, request, pk):
        """Clear chat history."""
        news = self.get_object()
        ChatSession.objects.filter(news=news).delete()
        return Response({'status': 'cleared'})

    def post(self, request, pk):
        from django.http import StreamingHttpResponse

        news = self.get_object()

        # Auto-fetch full article on first chat — so users don't have to click
        # "获取原文" before chatting. No-op if already cached, swallows fetch errors.
        ensure_full_content(news)

        # Pick the richest available context (full_content_zh > full_content > content_zh > content)
        context = pick_chat_context(news)
        if len(context) > 10000:
            context = context[-10000:]

        user_question = request.data.get('question', '').strip()
        if not user_question:
            return Response({'error': '问题不能为空'}, status=400)

        web_search = request.data.get('web_search', False)

        # Web search via research agent's tool — inject results into context
        web_context = ''
        if web_search:
            try:
                from api.services.research.tools import _tool_search_web
                search_result = _tool_search_web(user_question, count=5)
                results = search_result.get('results', [])
                if results:
                    lines = []
                    for i, r in enumerate(results, 1):
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

        # Load or create session
        session, _ = ChatSession.objects.get_or_create(news=news, defaults={'messages': []})

        # Ensure session.messages is a list
        if not isinstance(session.messages, list):
            session.messages = []

        history = session.messages[-20:] # Keep last 20 turns for context

        # Build messages for LLM
        system_content = (
            f'你是一位专业的新闻助手。用户正在阅读一篇新闻文章，请基于以下文章内容回答用户的问题。\n\n'
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
        
        for msg in history:
            messages.append(msg)
        
        messages.append({'role': 'user', 'content': user_question})

        # Save user message immediately
        user_msg = {'role': 'user', 'content': user_question}
        session.messages.append(user_msg)
        session.save(update_fields=['messages'])

        def save_ai_response(accumulated):
            """Helper to save AI response after stream finishes"""
            ai_msg = {'role': 'assistant', 'content': accumulated}
            session.messages.append(ai_msg)
            session.save(update_fields=['messages'])

        def generate():
            full_response = []
            try:
                # Use stream_chat which has built-in provider failover
                for chunk in stream_chat(messages, max_tokens=16000, temperature=0.7):
                    full_response.append(chunk)
                    yield chunk
            except Exception as e:
                fallback = "抱歉，AI 服务暂时不可用，请稍后再试。"
                yield f"\n\n[{fallback}]"
                if not full_response:
                    full_response = [fallback]
            finally:
                # Save the full response to DB
                save_ai_response(''.join(full_response))

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

    def get_queryset(self):
        return Source.objects.annotate(news_count=Count('news'))


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
    queryset = News.objects.select_related('source', 'category').all()
    permission_classes = []

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        import json
        from django.utils import timezone

        news = self.get_object()

        # ?force=1 from frontend "换一批" button — skip cache, force fresh LLM call.
        # On failure we keep the old cache (see except branch), so this is safe.
        force = request.query_params.get('force') in ('1', 'true', 'True')

        # Cache hit (unless forced)
        if not force and news.suggested_questions and len(news.suggested_questions) >= 3:
            return Response({'questions': news.suggested_questions[:3]})

        # Auto-fetch full article so suggestions are based on the real body,
        # not the short list-preview blurb. No-op if already cached.
        ensure_full_content(news)

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
            f'## 正文\n{context}'
        )

        try:
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

            news.suggested_questions = questions
            news.suggested_questions_generated_at = timezone.now()
            news.save(update_fields=['suggested_questions', 'suggested_questions_generated_at'])
            return Response({'questions': questions})
        except Exception as e:
            # Fall back silently — UX should never show "loading questions failed"
            import logging
            logging.getLogger(__name__).warning('suggested-questions LLM failed: %s', e)
            return Response({'questions': SUGGESTED_QUESTIONS_FALLBACK})


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

@api_view(['GET'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
    """GET /api/auth/csrf/ — returns CSRF token for SPA to include in subsequent requests."""
    return Response({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def auth_register(request):
    """POST /api/auth/register/ — create a new user and log them in."""
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')
    email = request.data.get('email', '')

    if not username or not password:
        return Response({'error': '用户名和密码不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if len(password) < 6:
        return Response({'error': '密码至少 6 位'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=username).exists():
        return Response({'error': '用户名已被占用'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=username, email=email, password=password)
    login(request, user)
    return Response({
        'id': user.pk,
        'username': user.username,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def auth_login(request):
    """POST /api/auth/login/ — authenticate and create a session."""
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'error': '用户名或密码错误'}, status=status.HTTP_401_UNAUTHORIZED)

    login(request, user)
    return Response({
        'id': user.pk,
        'username': user.username,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def auth_logout(request):
    """POST /api/auth/logout/ — end the current session."""
    logout(request)
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auth_me(request):
    """GET /api/auth/me/ — return current user info."""
    return Response({
        'id': request.user.pk,
        'username': request.user.username,
    })


# ─── TTS (Text-to-Speech) API ──────────────────────────────────────────

class NewsTTSView(generics.GenericAPIView):
    """Stream TTS audio for a news article using Edge TTS (Microsoft Natural voices).

    GET /api/news/<pk>/tts/?displayMode=zh&voice=yunyang&scope=full

    scope: 'summary' (title + short blurb) or 'full' (title + full article).
    Returns audio/mpeg stream. Supports caching — repeat requests serve from cache.
    """
    queryset = News.objects.select_related('source', 'category').all()
    permission_classes = []

    def get(self, request, pk):
        import asyncio
        import edge_tts
        from django.http import StreamingHttpResponse, FileResponse
        from api.services.tts_service import (
            clean_for_tts, pick_tts_voice, get_cached_audio, save_to_cache,
        )

        news = self.get_object()

        # Resolve parameters
        display_mode = request.query_params.get('displayMode', 'zh')
        voice_pref = request.query_params.get('voice', '')
        scope = request.query_params.get('scope', 'full')

        is_en = news.source.language == 'en'
        has_zh = is_en and bool(news.title_zh)

        # Pick voice
        voice = pick_tts_voice(
            source_language=news.source.language,
            display_mode=display_mode,
            has_zh=has_zh,
            voice_pref=voice_pref,
        )

        # Check cache first (scope is part of the cache key)
        cached = get_cached_audio(pk, display_mode, voice + ':' + scope)
        if cached:
            return FileResponse(
                open(cached, 'rb'),
                content_type='audio/mpeg',
                as_attachment=False,
            )

        # Resolve the text to speak
        if has_zh and display_mode != 'original':
            if scope == 'full':
                content = news.full_content_zh or news.content_zh or news.full_content or news.content or ''
            else:
                content = news.content_zh or news.content or ''
            title = news.title_zh or news.title
        else:
            if scope == 'full':
                content = news.full_content or news.content or ''
            else:
                content = news.content or ''
            title = news.title

        # Clean Markdown for natural speech
        clean_content = clean_for_tts(content)
        clean_title = clean_for_tts(title)
        speech_text = f'{clean_title}。{clean_content}'

        if not speech_text.strip():
            return Response({'error': '没有可朗读的内容'}, status=400)

        # Generate via Edge TTS, collect bytes, cache, then stream
        audio_chunks = []

        def generate_and_stream():
            loop = asyncio.new_event_loop()
            try:
                async def _gen():
                    communicate = edge_tts.Communicate(speech_text, voice)
                    async for chunk in communicate.stream():
                        if chunk.get('type') == 'audio' and 'data' in chunk:
                            yield chunk['data']

                gen = _gen()
                while True:
                    try:
                        chunk = loop.run_until_complete(gen.__anext__())
                        audio_chunks.append(chunk)
                        yield chunk
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()
                # Save to cache after generation completes
                if audio_chunks:
                    try:
                        save_to_cache(pk, display_mode, voice + ':' + scope, b''.join(audio_chunks))
                    except Exception:
                        pass  # Cache write failure is non-critical

        response = StreamingHttpResponse(
            generate_and_stream(),
            content_type='audio/mpeg',
        )
        response['Cache-Control'] = 'public, max-age=86400'
        return response
