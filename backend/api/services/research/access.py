"""Reauthorize persisted local evidence before research replay or continuation."""
from django.http import Http404
from api.rss.access import get_stored_article
from api.services.stored_readers import snapshot_metadata


def _search_article_is_current(user, row, *, id_key='id', require_snippet=True, require_url=True):
    if not isinstance(row, dict) or type(row.get(id_key)) is not int:
        return False
    try:
        stored = get_stored_article(user, row[id_key])
    except (Http404, ValueError, TypeError):
        return False
    expected = snapshot_metadata(stored)
    return (
        all(row.get(key) == value for key, value in expected.items())
        and row.get('source_scope') == stored.scope
        and row.get('policy_versions') == stored.policy_versions
        and row.get('title') == stored.title
        and (not require_snippet or row.get('snippet') == stored.summary[:200])
        and (not require_url or row.get('url') == stored.url)
    )


def _fetch_article_payload_is_current(user, data, stored):
    from api.models import News
    from api.rss.access import article_sources

    try:
        news = News.objects.get(pk=stored.news_id)
    except News.DoesNotExist:
        return False
    source = article_sources(user, news).select_related('publication').first()
    if source is None:
        return False
    truncated = len(stored.markdown) > 12000
    expected = dict(
        id=stored.news_id,
        title=stored.title,
        title_zh='',
        url=stored.url,
        source=source.publication.display_name or source.name,
        source_type=source.source_type,
        content=stored.markdown[:12000],
        content_truncated=truncated,
        original_length=len(stored.markdown),
        **{
            **snapshot_metadata(stored),
            'context_scope': 'excerpt' if truncated else stored.scope,
        },
        source_scope=stored.scope,
        policy_versions=stored.policy_versions,
        task_outcome='stored',
        publish_time=news.publish_time.isoformat() if news.publish_time else None,
    )
    # Replay validates the exact post-dispatch shape. Long payloads are capped
    # by execute_tool before storage, so compare against that same pure transform.
    from api.services.research.tools import _truncate_result
    expected = _truncate_result(expected)
    return type(data.get('id')) is int and data == expected


def result_is_current(user, tool_name, data):
    if not isinstance(data, dict):
        return False
    if tool_name in ('search_news', 'analyze_topic') and data == {
            'error': '研究工具暂时不可用，请稍后重试。'}:
        # execute_tool emits this exact sanitized failure without article evidence.
        return True
    if tool_name == 'search_news':
        articles = data.get('articles')
        return isinstance(articles, list) and all(
            _search_article_is_current(user, row) for row in articles
        )
    if tool_name == 'analyze_topic':
        articles = data.get('articles')
        timeline = data.get('timeline')
        if not isinstance(articles, list) or not isinstance(timeline, list):
            return False
        if not all(_search_article_is_current(user, row) for row in articles):
            return False
        for day in timeline:
            if not isinstance(day, dict) or not isinstance(day.get('events'), list):
                return False
            if not all(_search_article_is_current(user, event, id_key='article_id',
                    require_snippet=False, require_url=False) for event in day['events']):
                return False
        return True
    if tool_name in ('fetch_article', 'fetch_webpage'):
        if tool_name == 'fetch_webpage' and data.get('capability') == 'stored_articles_only':
            from api.rss.access import authorized_news
            url = data.get('url')
            expected = {
                'url': url,
                'content': '',
                'scope': 'summary',
                'context_scope': 'summary',
                'capability': 'stored_articles_only',
                'message': '此网页尚未收录；请使用已有搜索摘要与原文链接。',
            }
            return (
                isinstance(url, str)
                and data == expected
                and not authorized_news(user).filter(url=url).exists()
            )
        try:
            stored = get_stored_article(user, data.get('id'))
        except (Http404, ValueError, TypeError):
            return False
        return _fetch_article_payload_is_current(user, data, stored)
    return True


def require_session_evidence(session, user):
    # Older conversations can contain tool evidence without a search-result row.
    # Check the original OpenAI tool envelope as well, without changing history.
    import json
    calls = {}
    history = session.native_continuation.get('messages', session.messages) if isinstance(session.native_continuation, dict) else session.messages
    for message in history if isinstance(history, list) else []:
        if not isinstance(message, dict):
            continue
        for call in message.get('tool_calls', []) or []:
            if isinstance(call, dict):
                calls[call.get('id')] = call.get('function', {}).get('name')
        if message.get('role') == 'tool':
            name = calls.get(message.get('tool_call_id'), message.get('name'))
            if name in ('search_news', 'analyze_topic', 'fetch_article', 'fetch_webpage'):
                try:
                    data = json.loads(message.get('content', ''))
                except (ValueError, TypeError):
                    raise Http404 from None
                if not isinstance(data, dict) or not result_is_current(user, name, data):
                    raise Http404
    for row in session.search_results.all().only('tool_name', 'result_data'):
        if not result_is_current(user, row.tool_name, row.result_data):
            raise Http404('Research evidence is no longer available')
