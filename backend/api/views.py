from django.db.models import Count, Q
from rest_framework import generics, filters
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django_filters import rest_framework as django_filters
from .models import Category, Source, News, ChatSession
from .serializers import (
    CategorySerializer, SourceSerializer,
    NewsListSerializer, NewsDetailSerializer,
)


class CommaSeparatedIntegerFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class NewsFilter(django_filters.FilterSet):
    category = CommaSeparatedIntegerFilter(field_name='category', lookup_expr='in')
    source = CommaSeparatedIntegerFilter(field_name='source', lookup_expr='in')
    source__source_type = django_filters.CharFilter(field_name='source__source_type')

    class Meta:
        model = News
        fields = ['category', 'source', 'source__source_type']


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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['lang'] = self.request.query_params.get('lang', 'original')
        return context

    def get_queryset(self):
        # By default hide duplicates (entries with related_to set)
        if self.request.query_params.get('include_dupes', 'false') != 'true':
            return News.objects.select_related('source', 'category').filter(related_to__isnull=True)
        return News.objects.select_related('source', 'category').all()

    def list(self, request, *args, **kwargs):
        search_query = request.query_params.get('search', '').strip()
        mode = request.query_params.get('mode', 'keyword').strip()

        if not search_query or mode == 'keyword':
            return super().list(request, *args, **kwargs)

        if mode == 'semantic':
            return self._semantic_search(request, search_query)

        # mode == 'hybrid'
        return self._hybrid_search(request, search_query)

    def _semantic_search(self, request, query):
        from .services.vector_store import VectorStoreService
        from .services.embedding import EmbeddingService

        if not EmbeddingService.is_loaded():
            EmbeddingService.wait_until_ready(timeout=120)

        vs = VectorStoreService()
        if vs.count() == 0:
            return super().list(request, *[], **{})

        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        offset = (page - 1) * page_size
        n_results = offset + page_size

        results = vs.search(query, n=n_results)
        if not results:
            return self._empty_response(request)

        news_ids = [r[0] for r in results]
        total = len(news_ids)
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

        # Keyword search
        qs = self.filter_queryset(self.get_queryset())
        keyword_results = qs.filter(
            Q(title__icontains=query) | Q(content__icontains=query)
        )[:100]
        keyword_ids = [n.id for n in keyword_results]

        # Semantic search
        vs = VectorStoreService()
        semantic_ids = []
        if vs.count() > 0:
            results = vs.search(query, n=100)
            semantic_ids = [r[0] for r in results]

        # RRF fusion
        fused_ids = reciprocal_rank_fusion(keyword_ids, semantic_ids)

        if not fused_ids:
            return self._empty_response(request)

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

        total = len(fused_ids)
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


class NewsDetailView(generics.RetrieveAPIView):
    queryset = News.objects.select_related('source', 'category').all()
    serializer_class = NewsDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['lang'] = self.request.query_params.get('lang', 'original')
        return context


class NewsFetchFullView(generics.GenericAPIView):
    """Fetch full article content via Jina Reader API and persist to database."""
    queryset = News.objects.select_related('source', 'category').all()
    serializer_class = NewsDetailSerializer
    permission_classes = []  # Public access

    def post(self, request, pk):
        from django.utils.timezone import now as tz_now
        import urllib.request
        import ssl
        import re
        import logging

        logger = logging.getLogger(__name__)
        news = self.get_object()

        # If already has full content, return cached version
        if news.full_content:
            serializer = self.get_serializer(news)
            return Response(serializer.data)

        url = news.url
        if not url:
            return Response(
                {'error': 'No URL available for this article'},
                status=400,
            )

        jina_url = f'https://r.jina.ai/{url}'

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                jina_url,
                headers={'Accept': 'text/plain', 'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                text = resp.read().decode('utf-8')

            # Extract markdown content after "Markdown Content:" header
            markdown_match = re.search(r'Markdown Content:\n([\s\S]+)$', text)
            markdown = markdown_match.group(1).strip() if markdown_match else text.strip()

            if not markdown or markdown == 'Sorry.' or len(markdown) < 20:
                return Response(
                    {'error': '未能提取到有效内容'},
                    status=422,
                )

            # Clean page chrome for GitHub repo pages
            from api.services.content_cleaner import clean_content
            markdown = clean_content(markdown, url)

            # Save to database
            news.full_content = markdown
            news.full_content_fetched_at = tz_now()
            news.save(update_fields=['full_content', 'full_content_fetched_at'])

            serializer = self.get_serializer(news)
            return Response(serializer.data)

        except urllib.error.HTTPError as e:
            if e.code == 429:
                return Response(
                    {'error': '请求过于频繁，请稍后重试'},
                    status=429,
                )
            if e.code == 451:
                return Response(
                    {'error': '内容因法律限制无法获取'},
                    status=451,
                )
            logger.error(f'Jina Reader HTTP error for {url}: {e.code} - {e.reason}')
            return Response(
                {'error': f'获取失败 ({e.code})'},
                status=e.code,
            )
        except Exception as e:
            logger.error(f'Jina Reader error for {url}: {e}')
            return Response(
                {'error': f'获取失败: {str(e)}'},
                status=502,
            )


from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
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
        import time
        from api.services.llm_translator import _call_llm_stream

        news = self.get_object()

        force = request.data.get('force', False)

        # If already translated, stream existing result immediately (unless forced)
        if news.full_content_zh and not force:
            def existing_stream():
                data = json_lib.dumps({
                    'full_content_zh': news.full_content_zh,
                    'full_content_zh_fetched_at': news.full_content_zh_fetched_at.isoformat() if news.full_content_zh_fetched_at else None
                }, ensure_ascii=False)
                yield f"data: {data}\n\n"
            return StreamingHttpResponse(existing_stream(), content_type='text/event-stream')

        if not news.full_content:
            def error_stream():
                yield f"data: {json_lib.dumps({'error': '请先获取完整原文'})}\n\n"
            return StreamingHttpResponse(error_stream(), content_type='text/event-stream')

        # Check for existing translated link first
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

        prompt = f"请将以下 Markdown 文章翻译成中文：\n\n{context}"

        def translate_stream():
            full_text = []
            last_save_len = 0
            try:
                for chunk in _call_llm_stream(prompt):
                    full_text.append(chunk)
                    current_text = ''.join(full_text)
                    
                    # Save progress to DB every ~500 characters (in case client disconnects)
                    if len(current_text) - last_save_len >= 500:
                        news.full_content_zh = current_text
                        news.full_content_zh_fetched_at = timezone.now()
                        try:
                            news.save(update_fields=['full_content_zh', 'full_content_zh_fetched_at'])
                            last_save_len = len(current_text)
                        except Exception as save_err:
                            import logging
                            logging.getLogger(__name__).warning(f'Failed to save translation progress: {save_err}')
                    
                    # Yield progress
                    data = json_lib.dumps({'progress': current_text}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    # Small yield to force WSGI buffer flush if needed
                    time.sleep(0.01)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f'Translation failed: {e}')
                # Try to yield error, but ignore if client already disconnected
                try:
                    yield f"data: {json_lib.dumps({'error': str(e)})}\n\n"
                except Exception:
                    pass
                return

            # Final save
            translated = ''.join(full_text)
            if translated and not translated.startswith("Error:"):
                news.full_content_zh = translated
                news.full_content_zh_fetched_at = timezone.now()
                news.save(update_fields=['full_content_zh', 'full_content_zh_fetched_at'])

            yield f"event: complete\ndata: {json_lib.dumps({'full_content_zh': translated, 'full_content_zh_fetched_at': news.full_content_zh_fetched_at.isoformat()}, ensure_ascii=False)}\n\n"

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
        from api.services.llm_translator import get_openai_client

        news = self.get_object()
        
        context = news.full_content_zh if news.full_content_zh else news.content
        if len(context) > 10000:
            context = context[-10000:]

        user_question = request.data.get('question', '').strip()
        if not user_question:
            return Response({'error': '问题不能为空'}, status=400)

        # Load or create session
        session, _ = ChatSession.objects.get_or_create(news=news, defaults={'messages': []})
        
        # Ensure session.messages is a list
        if not isinstance(session.messages, list):
            session.messages = []

        history = session.messages[-20:] # Keep last 20 turns for context

        # Build messages for LLM
        messages = [
            {
                'role': 'system',
                'content': (
                    f'你是一位专业的新闻助手。用户正在阅读一篇新闻文章，请基于以下文章内容回答用户的问题。\n\n'
                    f'## 文章内容:\n{context}\n\n'
                    f'## 要求:\n'
                    f'1. 必须严格基于文章内容回答，不要编造信息。\n'
                    f'2. 如果文章中找不到答案，请明确告知用户。\n'
                    f'3. 回答要简洁、清晰、有逻辑。\n'
                    f'4. 使用 Markdown 格式，支持列表、加粗等。'
                )
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
                client = get_openai_client()
                stream = client.chat.completions.create(
                    model='kimi-k2.5',
                    messages=messages,
                    temperature=0.7,
                    stream=True,
                )

                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        full_response.append(delta.content)
                        yield delta.content
            except Exception as e:
                yield f"\n\n[Error: {str(e)}]"
            finally:
                # Save the full response to DB
                save_ai_response(''.join(full_response))

        return StreamingHttpResponse(generate(), content_type='text/event-stream')


class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.annotate(news_count=Count('news'))


class SourceListView(generics.ListAPIView):
    serializer_class = SourceSerializer

    def get_queryset(self):
        return Source.objects.annotate(news_count=Count('news'))
