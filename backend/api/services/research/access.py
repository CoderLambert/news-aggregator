"""Reauthorize persisted local evidence before research replay or continuation."""
from django.http import Http404
from api.rss.access import authorized_news, get_stored_article
from api.services.stored_readers import snapshot_metadata


def result_is_current(user, tool_name, data):
    if tool_name in ('search_news', 'analyze_topic'):
        ids = {row.get('id') for row in data.get('articles', []) if isinstance(row, dict)}
        return set(authorized_news(user).filter(pk__in=ids).values_list('pk', flat=True)) == ids
    if tool_name in ('fetch_article', 'fetch_webpage'):
        if data.get('capability') == 'stored_articles_only':
            return True
        try:
            stored = get_stored_article(user, data.get('id'))
        except (Http404, ValueError, TypeError):
            return False
        expected = snapshot_metadata(stored)
        return all(data.get(key) == value for key, value in expected.items() if key != 'context_scope') and data.get('source_scope') == stored.scope
    return True


def require_session_evidence(session, user):
    # Older conversations can contain tool evidence without a search-result row.
    # Check the original OpenAI tool envelope as well, without changing history.
    import json
    calls = {}
    for message in session.messages if isinstance(session.messages, list) else []:
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
