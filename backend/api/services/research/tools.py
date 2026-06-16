"""Tool definitions and execution for the research agent.

Each tool follows the OpenAI function-calling JSON schema. The `execute_tool`
dispatcher routes tool names to handler functions that return structured JSON.

Tool results are truncated to _MAX_RESULT_CHARS to prevent context overflow.
"""

import json
import logging
import ssl
import urllib.parse
import urllib.request
from datetime import timedelta
from collections import defaultdict

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8000

# Full conversational phrases to strip from queries
_CN_STOP_PHRASES = [
    '是什么', '是什么？', '是啥', '有哪些', '有哪', '有什么', '有那些',
    '怎么了', '怎么样', '什么样', '怎么样？', '如何', '如何？',
    '怎么', '怎么？', '为什么', '为什么？', '为啥', '为啥？',
    '什么意思', '什么意思？', '指的是什么', '指的什么',
    '帮我介绍', '帮我介绍下', '帮我介绍一下',
    '请介绍', '请介绍一下', '能否介绍', '能否介绍一下',
    '说说', '说说看', '讲讲', '讲一下', '了解下', '了解一下',
    '帮我', '帮', '说说',
    '情况如何', '情况怎样', '情况怎么样', '的情况',
    '相关信息', '详细信息',
    '呢', '吗', '吧', '啊', '呀', '哦', '嗯', '哎',
    '的', '了', '和', '与', '及', '及其',
    '什么', '啥', '哪些', '哪个', '哪些',
    '一个', '一些', '一种',
    '东西',
]


def _extract_search_query(user_question: str) -> tuple:
    """Extract optimized search keywords from a conversational question.

    Returns:
        (primary_query, secondary_query) — primary is the best query,
        secondary is an optional additional query for more coverage.
    """
    import re

    # Extract English words (product names, tech terms)
    en_words = re.findall(r'[A-Za-z][A-Za-z0-9.+#]*(?:[\s/-][A-Za-z0-9.+#]+)*', user_question)
    en_words = [w for w in en_words if len(w) > 1 or w in ('C', 'R', 'Go', 'AI')]

    # Extract all Chinese text (without English)
    cn_text = re.sub(r'[A-Za-z0-9.+#/\s]+', '', user_question)

    # Remove stop phrases (longest first)
    remaining = cn_text
    for phrase in sorted(_CN_STOP_PHRASES, key=len, reverse=True):
        remaining = remaining.replace(phrase, '')

    # Clean up
    remaining = re.sub(r'[？?！!，,。、；；\s]+', ' ', remaining).strip()
    # Keep only Chinese sequences
    cn_tokens = re.findall(r'[一-鿿]+', remaining)
    cn_tokens = [t for t in cn_tokens if len(t) >= 2]

    # Build primary and secondary queries
    if en_words:
        primary = ' '.join(en_words)
        if cn_tokens and len(cn_tokens) <= 3:
            secondary = ' '.join(cn_tokens) + ' ' + primary
            return secondary, None
        return primary, None
    else:
        if cn_tokens:
            cn_tokens.sort(key=len, reverse=True)
            primary = cn_tokens[0]
            if len(cn_tokens) > 1 and len(cn_tokens[1]) >= 2:
                secondary = cn_tokens[1]
                return primary, secondary
            return primary, None
        cleaned = re.sub(r'[？?！!，,。、；；\s]+', ' ', user_question).strip()
        if cleaned:
            return cleaned, None
        return user_question, None


# ── OpenAI function-calling tool schemas ────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "搜索本地新闻数据库。支持语义搜索、关键词搜索和混合搜索模式。"
                "返回匹配文章的标题、摘要、来源和日期。"
                "可选参数: "
                "- order_by: 结果排序方式, 'relevance'(按语义相关性) 或 'time'(按发布时间最新)。"
                  "当用户需要查找'最新的'、'最近的'文章时使用 order_by='time'。"
                "- full_content: 设为 true 时仅返回已抓取完整正文的文章。"
                  "当用户需要深度阅读、分析或需要完整内容时建议开启。"
                "- days: 限制为最近 N 天的文章。"
                "- source_type: 按来源类型过滤 ('news'/'aggregator'/'discussion')。"
                "- category: 按分类名称精确匹配过滤(如 'AI', '前端', '科技')。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言搜索查询",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["semantic", "keyword", "hybrid"],
                        "default": "hybrid",
                        "description": "搜索模式：semantic=语义搜索, keyword=关键词搜索, hybrid=混合搜索",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "maximum": 30,
                        "description": "返回结果数量上限",
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["news", "aggregator", "discussion"],
                        "description": "筛选新闻源类型",
                    },
                    "days": {
                        "type": "integer",
                        "description": "限制最近 N 天内的文章",
                    },
                    "order_by": {
                        "type": "string",
                        "enum": ["relevance", "time"],
                        "default": "relevance",
                        "description": "排序方式: relevance=按语义相关性, time=按发布时间从新到旧",
                    },
                    "full_content": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅返回已获取完整正文的文章",
                    },
                    "category": {
                        "type": "string",
                        "description": "按分类名称过滤, 例如 'AI', '前端', '科技', '安全' 等",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_article",
            "description": (
                "获取指定新闻文章的完整内容。返回文章标题、来源、URL 和正文（Markdown）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "integer",
                        "description": "文章的数据库 ID",
                    },
                },
                "required": ["article_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "搜索互联网获取本地新闻库之外的补充信息。返回标题、摘要和 URL。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "网络搜索查询",
                    },
                    "count": {
                        "type": "integer",
                        "default": 5,
                        "maximum": 10,
                        "description": "返回结果数量",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": (
                "抓取并提取指定 URL 的文本内容。适用于阅读通过搜索找到的完整文章。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页 URL",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_topic",
            "description": (
                "对特定话题进行深度分析：搜索相关文章、按时间段分组、发现关联事件、生成时间线。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要分析的话题或事件",
                    },
                    "depth": {
                        "type": "string",
                        "enum": ["quick", "standard", "deep"],
                        "default": "standard",
                        "description": "分析深度：quick=快速概览, standard=标准分析, deep=深度分析",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": (
                "基于已收集的信息生成结构化研究报告，并进行质量检查。"
                "调用此工具前确保已经收集了足够的信息，包含所有必要的来源引用。"
                "当信息充足、可以给出全面回答时，调用此工具来组织最终输出。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "研究主题或问题",
                    },
                    "sections": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "报告应包含的章节标题",
                    },
                    "include_timeline": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否包含事件时间线",
                    },
                    "quality_check": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否执行质量检查，确保报告符合标准",
                    },
                },
                "required": ["topic"],
            },
        },
    },
]


# ── Tool dispatcher ─────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict, session=None) -> dict:
    """Execute a tool by name with the given arguments.

    Returns a structured JSON dict. Each handler must return a dict that can
    be serialized to JSON and truncated to _MAX_RESULT_CHARS.

    If *session* (a ResearchSession instance) is provided and the result is
    successful, the result is persisted to ResearchSearchResult automatically.
    """
    tool_map = {
        'search_news': _tool_search_news,
        'fetch_article': _tool_fetch_article,
        'search_web': _tool_search_web,
        'fetch_webpage': _tool_fetch_webpage,
        'analyze_topic': _tool_analyze_topic,
        'generate_report': _tool_generate_report,
    }
    handler = tool_map.get(name)
    if not handler:
        return {'error': f'Unknown tool: {name}'}
    try:
        result = handler(**args)
        result = _truncate_result(result)

        # Persist search result if session is provided and no error
        if session is not None and 'error' not in result:
            _save_search_result(session, name, args, result)

        return result
    except Exception as e:
        logger.exception('Tool %s failed', name)
        return {'error': str(e)}


def _save_search_result(session, tool_name: str, args: dict, result: dict):
    """Extract summary fields from a tool result and persist to the database."""
    from api.models import ResearchSearchResult

    # Map tool_name → (result_type, extracted_fields)
    field_map = {
        'search_news': lambda: (
            'news',
            args.get('query', ''),
            '',                                     # source (multiple articles)
            '',                                     # title
            '',                                     # url
            result.get('total', 0),                 # hit_count
        ),
        'search_web': lambda: (
            'web',
            args.get('query', ''),
            result.get('source', ''),               # jina / wikipedia / duckduckgo
            '',                                     # title
            '',                                     # url
            len(result.get('results', [])),          # hit_count
        ),
        'fetch_article': lambda: (
            'article',
            '',
            result.get('source', ''),
            result.get('title_zh', '') or result.get('title', ''),
            result.get('url', ''),
            result.get('original_length', 0),
        ),
        'fetch_webpage': lambda: (
            'webpage',
            '',
            '',
            '',
            result.get('url', ''),
            result.get('length', 0),
        ),
        'analyze_topic': lambda: (
            'topic',
            args.get('query', ''),
            '',
            '',
            '',
            result.get('total_articles', 0),
        ),
    }

    extractor = field_map.get(tool_name)
    if not extractor:
        return

    try:
        result_type, query, source, title, url, hit_count = extractor()
        ResearchSearchResult.objects.create(
            session=session,
            tool_name=tool_name,
            query=query,
            result_data=result,
            result_type=result_type,
            source=source,
            title=title,
            url=url,
            hit_count=hit_count,
        )
    except Exception as e:
        # Persistence failure should never break the agent loop
        logger.warning('Failed to save search result: %s', e)


# ── Helper: truncate large results ──────────────────────────────────────────

def _truncate_result(result: dict) -> dict:
    """Ensure the JSON-serialized result does not exceed _MAX_RESULT_CHARS.

    Uses head+tail preservation for text fields and caps list length at 20.
    """
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= _MAX_RESULT_CHARS:
        return result
    # Truncate large text fields with head+tail preservation
    for key, val in list(result.items()):
        if isinstance(val, str) and len(val) > 1000:
            head = val[:600]
            tail = val[-200:]
            result[key] = head + '...[内容已截断]...' + tail
        elif isinstance(val, list):
            result[key] = val[:20]  # Cap list length
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > _MAX_RESULT_CHARS:
        result = {'_summary': text[:_MAX_RESULT_CHARS - 20] + '...[truncated]'}
    return result


# ── SSRF protection: blocked URL patterns ───────────────────────────────────

import ipaddress
import socket

# Private/reserved IP ranges that should never be fetched
_BLOCKED_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]

# Hostnames that should never be fetched
_BLOCKED_HOSTNAMES = {
    'localhost', 'metadata.google.internal', 'metadata.azure.com',
    '169.254.169.254',
}


def _is_url_allowed(url: str) -> tuple[bool, str]:
    """Validate that a URL is safe to fetch (blocks internal IPs and hostnames).

    Returns (allowed, reason) — reason is empty if allowed.
    """
    parsed = urllib.parse.urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ('http', 'https'):
        return False, f'Unsupported scheme: {parsed.scheme}'

    hostname = parsed.hostname
    if not hostname:
        return False, 'Missing hostname'

    # Block known internal hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in _BLOCKED_HOSTNAMES:
        return False, f'Blocked hostname: {hostname}'

    # Resolve the hostname and check against private IP ranges
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
                if hasattr(ip, 'ipv4_mapped') and ip.ipv4_mapped:
                    ip = ip.ipv4_mapped
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        return False, f'Blocked internal IP: {ip_str}'
            except ValueError:
                continue
    except socket.gaierror:
        # DNS resolution failed — let it fail naturally at fetch time
        pass

    return True, ''

def _reciprocal_rank_fusion(*ranked_lists, k=60):
    scores = {}
    for ranked_ids in ranked_lists:
        for rank, nid in enumerate(ranked_ids):
            scores[nid] = scores.get(nid, 0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


# ── Tool implementations ────────────────────────────────────────────────────

def _generate_query_variations(query: str) -> list[str]:
    """Generate search query variations for broader coverage.

    Returns a list of query strings including the original.
    """
    variations = [query]
    if len(query) <= 4:
        return variations

    # Shorter version (first half)
    half = query[:len(query) // 2].strip()
    if half and half != query:
        variations.append(half)

    # Remove common Chinese stopwords and keep core terms
    cn_stopwords = {
        '的', '了', '和', '是', '在', '我', '有', '就', '都', '而',
        '及', '与', '等', '最新', '进展', '突破', '发展', '趋势',
        '落地', '案例', '应用', '如何', '什么', '怎么', '哪些',
        '为什么', '怎样', '关于', '对于', '目前', '现在', '近期',
    }
    terms = [t for t in query.replace('？', ' ').replace('?', ' ').split()
             if t not in cn_stopwords and len(t) >= 2]
    if len(terms) >= 2:
        core_terms = ' '.join(terms[:3])
        if core_terms != query:
            variations.append(core_terms)

    return variations[:3]  # Cap at 3 variations to control cost


def _tool_search_news(query: str, mode: str = 'hybrid', limit: int = 10,
                      source_type: str | None = None, days: int | None = None,
                      order_by: str = 'relevance', full_content: bool = False,
                      category: str | None = None) -> dict:
    """Search the local news database using keyword, semantic, or hybrid mode.

    Uses multiple query variations for broader coverage.
    Supports time filtering, ordering, content filtering, and category filtering.
    """
    from api.models import News
    from api.services.vector_store import VectorStoreService

    limit = min(limit, 30)
    qs = News.objects.select_related('source', 'category')

    # Time filter
    if days:
        qs = qs.filter(publish_time__gte=timezone.now() - timedelta(days=days))

    # Source type filter
    if source_type:
        qs = qs.filter(source__source_type=source_type)

    # Full content filter
    if full_content:
        qs = qs.filter(full_content_fetch_status='success')

    # Category filter (by name, case-insensitive)
    if category:
        qs = qs.filter(category__name__iexact=category)

    # Generate query variations for broader coverage
    query_variations = _generate_query_variations(query)

    if mode == 'keyword':
        # Fetch more results initially to allow for re-ordering
        fetch_limit = limit * 3 if order_by == 'time' else limit
        all_articles = []
        seen_ids = set()
        for q in query_variations:
            filtered = qs.filter(
                Q(title__icontains=q) | Q(content__icontains=q)
                | Q(title_zh__icontains=q) | Q(content_zh__icontains=q)
            )[:fetch_limit]
            for art in filtered:
                if art.id not in seen_ids:
                    seen_ids.add(art.id)
                    all_articles.append(art)
            if len(all_articles) >= fetch_limit:
                break

        # Re-order by publish time if requested
        if order_by == 'time' and all_articles:
            ids = [a.id for a in all_articles]
            ordered_qs = News.objects.filter(id__in=ids).order_by('-publish_time')
            id_to_article = {a.id: a for a in all_articles}
            all_articles = [id_to_article[n.id] for n in ordered_qs if n.id in id_to_article]

        articles = _serialize_news_list(all_articles[:limit])

    elif mode == 'semantic':
        vs = VectorStoreService()
        if vs.count() == 0:
            return {'articles': [], 'total': 0, 'query': query, 'mode': mode,
                    'variations_used': query_variations}
        # Fetch more results to allow for re-ordering
        fetch_n = limit * 3 if order_by == 'time' else limit
        all_ids = []
        seen_ids = set()
        for q in query_variations:
            results = vs.search(q, n=fetch_n)
            for nid, _ in results:
                if nid not in seen_ids:
                    seen_ids.add(nid)
                    all_ids.append(nid)
        if not all_ids:
            return {'articles': [], 'total': 0, 'query': query, 'mode': mode,
                    'variations_used': query_variations}

        # Re-order by publish time if requested
        if order_by == 'time':
            time_ordered = News.objects.filter(id__in=all_ids).order_by('-publish_time').values_list('id', flat=True)
            all_ids = list(time_ordered)

        news_map = News.objects.select_related('source', 'category').in_bulk(all_ids)
        ordered = [news_map[nid] for nid in all_ids if nid in news_map]
        articles = _serialize_news_list(ordered[:limit])

    else:  # hybrid
        # Keyword branch with variations
        keyword_ids = []
        keyword_seen = set()
        for q in query_variations:
            keyword_qs = qs.filter(
                Q(title__icontains=q) | Q(content__icontains=q)
                | Q(title_zh__icontains=q) | Q(content_zh__icontains=q)
            )[:100]
            for n in keyword_qs:
                if n.id not in keyword_seen:
                    keyword_seen.add(n.id)
                    keyword_ids.append(n.id)

        # Semantic branch with variations
        vs = VectorStoreService()
        semantic_ids = []
        semantic_seen = set()
        if vs.count() > 0:
            for q in query_variations:
                results = vs.search(q, n=100)
                for nid, _ in results:
                    if nid not in semantic_seen:
                        semantic_seen.add(nid)
                        semantic_ids.append(nid)

        fused_ids = _reciprocal_rank_fusion(keyword_ids, semantic_ids)
        if not fused_ids:
            return {'articles': [], 'total': 0, 'query': query, 'mode': mode,
                    'variations_used': query_variations}

        # Re-order by publish time if requested
        if order_by == 'time':
            time_ordered = News.objects.filter(id__in=fused_ids).order_by('-publish_time').values_list('id', flat=True)
            fused_ids = list(time_ordered)

        fused_ids = fused_ids[:limit]
        news_map = News.objects.select_related('source', 'category').in_bulk(fused_ids)
        ordered = [news_map[nid] for nid in fused_ids if nid in news_map]
        articles = _serialize_news_list(ordered)

    return {
        'articles': articles,
        'total': len(articles),
        'query': query,
        'mode': mode,
        'order_by': order_by,
        'variations_used': query_variations,
    }


def _tool_fetch_article(article_id: int) -> dict:
    """Fetch the full content of a specific article by its database ID.

    Priority:
      1. Return existing full content from the database (if available).
      2. If no full content yet, try to fetch it from the original URL
         and persist to the database, then return the newly fetched text.
    """
    from api.models import News
    from api.views import pick_chat_context, ensure_full_content

    try:
        news = News.objects.select_related('source', 'category').get(pk=article_id)
    except News.DoesNotExist:
        return {'error': f'Article {article_id} not found'}

    # If we have full content already, return it immediately
    content = pick_chat_context(news)
    if news.full_content or news.full_content_zh:
        max_chars = 12000
        truncated = len(content) > max_chars
        return {
            'id': news.id,
            'title': news.title,
            'title_zh': news.title_zh,
            'source': news.source.name,
            'source_type': news.source.source_type,
            'category': news.category.name,
            'url': news.url,
            'content': content[:max_chars],
            'content_truncated': truncated,
            'original_length': len(content),
            'publish_time': news.publish_time.isoformat() if news.publish_time else None,
        }

    # No full content yet — try to fetch it from the original URL
    if news.url:
        ensure_full_content(news)
        # Refresh from DB to get the newly fetched content
        news.refresh_from_db()
        content = pick_chat_context(news)

    max_chars = 12000
    truncated = len(content) > max_chars
    return {
        'id': news.id,
        'title': news.title,
        'title_zh': news.title_zh,
        'source': news.source.name,
        'source_type': news.source.source_type,
        'category': news.category.name,
        'url': news.url,
        'content': content[:max_chars],
        'content_truncated': truncated,
        'original_length': len(content),
        'publish_time': news.publish_time.isoformat() if news.publish_time else None,
    }


def _tool_search_web(query: str, count: int = 5) -> dict:
    """Search the web with multiple fallback sources.

    Try order:
    1. Jina AI Search (needs API key, best quality)
    2. Wikipedia OpenSearch (free, no auth, good for factual queries)
    3. DuckDuckGo HTML (may be rate-limited / CAPTCHA)
    """
    count = min(count, 10)
    errors = []

    # 1) Try Jina AI Search
    try:
        search_url = f'https://s.jina.ai/{urllib.parse.quote(query)}'
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        import os
        jina_key = os.environ.get('JINA_API_KEY', '')
        if jina_key:
            headers['Authorization'] = f'Bearer {jina_key}'

        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(
            req, timeout=15, context=ssl.create_default_context()
        ) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        results = []
        for item in data.get('data', [])[:count]:
            results.append({
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'snippet': (item.get('content', '') or '')[:300],
                'source': 'jina',
            })
        if results:
            return {'results': results, 'query': query, 'source': 'jina'}

    except Exception as e:
        errors.append(f'Jina: {e}')
        logger.info('Jina search failed, trying fallbacks: %s', e)

    # 2) Wikipedia OpenSearch (always available, no auth needed)
    try:
        wiki_results = _wikipedia_search(query, count)
        if wiki_results:
            return {'results': wiki_results, 'query': query, 'source': 'wikipedia'}
    except Exception as e:
        errors.append(f'Wikipedia: {e}')
        logger.info('Wikipedia search failed: %s', e)

    # 3) DuckDuckGo HTML fallback (may be rate-limited)
    try:
        ddg_result = _duckduckgo_search(query, count)
        if ddg_result and ddg_result.get('results'):
            return ddg_result
    except Exception as e:
        errors.append(f'DuckDuckGo: {e}')
        logger.warning('DuckDuckGo fallback also failed: %s', e)

    # All sources failed — return structured error with guidance
    return {
        'results': [],
        'query': query,
        'error': '联网搜索暂时不可用',
        'error_details': errors,
        'recommendation': (
            '建议：\n'
            '1. 配置 JINA_API_KEY 以启用高质量联网搜索\n'
            '2. 尝试简化搜索关键词\n'
            '3. 使用本地新闻库搜索相关内容'
        ),
    }


def _wikipedia_search(query: str, count: int) -> list[dict]:
    """Search Wikipedia via the API. Free, no authentication needed.

    Uses the search API for richer results. For long Chinese queries,
    we extract key terms to improve match rate on Wikipedia.
    """
    import re

    # Simplify long Chinese queries for better Wikipedia matching
    # Keep only the most important terms (nouns, proper nouns)
    simplified = query
    if len(query) > 15:
        # For Chinese: extract 2-3 key terms by splitting on common stopwords
        cn_stopwords = {'最新', '进展', '突破', '发展', '趋势', '落地', '案例', '应用'}
        terms = re.findall(r'[一-鿿A-Za-z0-9]+', query)
        key_terms = [t for t in terms if t not in cn_stopwords and len(t) >= 2]
        if key_terms:
            simplified = ' '.join(key_terms[:3])

    results = []

    # Try both English and Chinese Wikipedia
    for lang in ['en', 'zh']:
        # Use Wikipedia's search API with both original and simplified query
        search_q = simplified if lang == 'en' else query
        url = (
            f'https://{lang}.wikipedia.org/w/api.php'
            f'?action=query'
            f'&list=search'
            f'&srsearch={urllib.parse.quote(search_q)}'
            f'&srlimit={count}'
            f'&srprop=snippet|titlesnippet|timestamp'
            f'&utf8=&format=json'
        )
        req = urllib.request.Request(url, headers={
            'User-Agent': 'NewsHub/1.0 (research agent)',
        })
        with urllib.request.urlopen(
            req, timeout=10, context=ssl.create_default_context()
        ) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        search_results = data.get('query', {}).get('search', [])
        for item in search_results[:count]:
            title = item.get('title', '')
            snippet = item.get('snippet', '')
            page_id = item.get('pageid')

            # Build Wikipedia URL
            page_url = ''
            if page_id:
                page_url = f'https://{lang}.wikipedia.org/?curid={page_id}'

            # Strip HTML tags from snippet
            clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip() if snippet else ''

            if title:
                results.append({
                    'title': title,
                    'url': page_url,
                    'snippet': clean_snippet[:300],
                    'source': f'wikipedia_{lang}',
                    'timestamp': item.get('timestamp', ''),
                })

        if results:
            return results

    return []


def _duckduckgo_search(query: str, count: int) -> dict:
    """Fallback web search via DuckDuckGo HTML with improved parsing resilience."""
    import re

    search_url = f'https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}'
    req = urllib.request.Request(search_url, headers={
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'Referer': 'https://duckduckgo.com/',
    })
    with urllib.request.urlopen(
        req, timeout=20, context=ssl.create_default_context()
    ) as resp:
        html = resp.read().decode('utf-8', errors='replace')

    # Parse results from DDG HTML with more resilient patterns
    results = []

    # Try block-level parsing first (more resilient to layout changes)
    # Use a greedy match to capture the full result block including nested divs
    result_blocks = re.findall(
        r'<div[^>]+class="result results_links[^"]*"[^>]*>(.*?)'
        r'<div class="clear"></div>',
        html, re.DOTALL,
    )
    if result_blocks:
        for block in result_blocks[:count]:
            link_match = re.search(
                r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                block, re.DOTALL,
            )
            if not link_match:
                continue
            url, title = link_match.groups()

            # Try multiple patterns for snippet — DDG varies by query
            snippet = ''
            for pattern in [
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                r'<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
                r'<span[^>]+class="result__snippet"[^>]*>(.*?)</span>',
            ]:
                m = re.search(pattern, block, re.DOTALL)
                if m:
                    snippet = m.group(1)
                    break

            # Process URL (DDG redirects)
            if 'uddg=' in url:
                actual_url = urllib.parse.unquote(
                    url.split('uddg=')[-1].split('&')[0]
                )
            else:
                actual_url = url

            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:300]

            if clean_title:
                results.append({
                    'title': clean_title,
                    'url': actual_url,
                    'snippet': clean_snippet,
                    'source': 'duckduckgo',
                })
    else:
        # Fallback to simple link+snippet pattern matching
        link_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<(?:a|div|span|td)[^>]+class="result__snippet"[^>]*>(.*?)</(?:a|div|span|td)>',
            re.DOTALL,
        )
        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links[:count]):
            if 'uddg=' in url:
                actual_url = urllib.parse.unquote(
                    url.split('uddg=')[-1].split('&')[0]
                )
            else:
                actual_url = url

            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            clean_snippet = ''
            if i < len(snippets):
                clean_snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()[:300]

            if clean_title:
                results.append({
                    'title': clean_title,
                    'url': actual_url,
                    'snippet': clean_snippet,
                    'source': 'duckduckgo',
                })

    return {'results': results, 'query': query, 'source': 'duckduckgo'}


def _tool_fetch_webpage(url: str) -> dict:
    """Fetch and extract text content from a URL using Jina Reader."""
    # SSRF protection: validate URL before fetching
    allowed, reason = _is_url_allowed(url)
    if not allowed:
        logger.warning('SSRF blocked: %s (%s)', url, reason)
        return {'url': url, 'error': f'URL not allowed: {reason}', 'content': ''}

    try:
        jina_url = f'https://r.jina.ai/{url}'
        headers = {
            'Accept': 'text/plain',
            'User-Agent': 'Mozilla/5.0',
        }
        import os
        jina_key = os.environ.get('JINA_API_KEY', '')
        if jina_key:
            headers['Authorization'] = f'Bearer {jina_key}'

        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(
            req, timeout=30, context=ssl.create_default_context()
        ) as resp:
            content = resp.read().decode('utf-8')

        return {
            'url': url,
            'content': content[:6000],
            'length': len(content),
        }

    except Exception as e:
        logger.warning('Fetch webpage failed for %s: %s', url, e)
        return {'url': url, 'error': str(e), 'content': ''}


def _tool_analyze_topic(query: str, depth: str = 'standard') -> dict:
    """Analyze a topic across multiple articles with timeline generation."""
    from api.models import News
    from api.services.vector_store import VectorStoreService

    depth_limits = {'quick': 5, 'standard': 15, 'deep': 30}
    limit = depth_limits.get(depth, 15)

    # Search with multiple query variations
    all_ids = set()
    queries = [query]
    # Simple variation: try shorter version
    if len(query) > 4:
        queries.append(query[:len(query) // 2])

    vs = VectorStoreService()
    if vs.count() > 0:
        for q in queries:
            results = vs.search(q, n=limit)
            for nid, _ in results:
                all_ids.add(nid)

    # Also try keyword match
    keyword_news = News.objects.filter(
        Q(title__icontains=query) | Q(content__icontains=query)
        | Q(title_zh__icontains=query) | Q(content_zh__icontains=query)
    ).values_list('id', flat=True)[:limit]
    all_ids.update(keyword_news)

    if not all_ids:
        return {
            'topic': query,
            'articles': [],
            'timeline': [],
            'related_topics': [],
            'depth': depth,
        }

    # Fetch articles and build timeline
    articles_qs = News.objects.select_related('source', 'category').filter(
        id__in=all_ids
    ).order_by('-publish_time')[:limit]

    articles = _serialize_news_list(articles_qs)

    # Group by date for timeline
    time_groups = defaultdict(list)
    for art in articles_qs:
        if art.publish_time:
            day_key = art.publish_time.strftime('%Y-%m-%d')
            time_groups[day_key].append({
                'title': art.title_zh or art.title,
                'article_id': art.id,
                'source': art.source.name,
            })

    timeline = []
    for date in sorted(time_groups.keys(), reverse=True):
        timeline.append({
            'date': date,
            'events': time_groups[date],
        })

    # Discover related topics via category distribution
    categories = defaultdict(int)
    for art in articles_qs:
        categories[art.category.name] += 1
    related_topics = sorted(categories, key=categories.get, reverse=True)[:5]

    return {
        'topic': query,
        'articles': articles,
        'timeline': timeline,
        'related_topics': related_topics,
        'total_articles': len(articles),
        'depth': depth,
    }


def _tool_generate_report(topic: str, sections: list | None = None,
                          include_timeline: bool = False,
                          quality_check: bool = True) -> dict:
    """Meta-tool: signal the agent to structure its final response with quality control.

    Returns suggested report structure and quality checklist for the agent to follow.
    """
    default_sections = [
        '核心摘要',
        '关键发现',
        '详细分析',
        '来源与参考',
    ]
    if include_timeline:
        default_sections.insert(2, '事件时间线')

    quality_checklist = []
    if quality_check:
        quality_checklist = [
            '✓ 每个论断都有来源引用',
            '✓ 关键事实已通过至少2个独立来源验证',
            '✓ 信息冲突已明确标注并说明',
            '✓ 没有编造或推测的信息',
            '✓ 时间线准确且按顺序排列',
            '✓ 来源列表完整可追溯',
        ]

    return {
        'topic': topic,
        'suggested_sections': sections or default_sections,
        'include_timeline': include_timeline,
        'quality_checklist': quality_checklist,
        'instruction': (
            '请按照以上章节结构组织你的最终回答，确保符合质量检查要求。'
            '每个论断都标注来源，使用 Markdown 格式。'
            '如果信息不足，在相应章节明确说明「暂未找到相关信息」。'
        ),
    }


# ── Serialization helpers ───────────────────────────────────────────────────

def _serialize_news_list(news_list) -> list[dict]:
    """Convert a queryset/list of News objects to a lightweight dict list."""
    results = []
    for n in news_list:
        snippet = (n.content_zh or n.content or '')[:200]
        results.append({
            'id': n.id,
            'title': n.title_zh or n.title,
            'original_title': n.title if n.title_zh else '',
            'source': n.source.name,
            'source_type': n.source.source_type,
            'category': n.category.name,
            'url': n.url,
            'snippet': snippet,
            'publish_time': n.publish_time.isoformat() if n.publish_time else None,
        })
    return results
