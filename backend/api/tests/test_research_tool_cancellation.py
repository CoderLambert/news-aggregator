"""F02: cancellation must stop new provider and tool network operations."""
from types import SimpleNamespace

import pytest

from api.services.research import agent_loop, tools


class Stopped(Exception):
    pass


def cancel_guard(flag):
    def guard():
        if flag['cancelled']:
            raise Stopped('research run cancelled')
    return guard


def test_llm_fallback_and_retry_do_not_call_a_second_provider_after_cancel(monkeypatch):
    state = {'cancelled': False}
    calls = []

    def provider(name):
        def create(**kwargs):
            calls.append(name)
            state['cancelled'] = True
            raise TimeoutError('first provider already timed out')
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(agent_loop, 'get_clients', lambda: [
        (provider('first'), 'first-model'), (provider('second'), 'second-model'),
    ])
    with pytest.raises(Stopped):
        agent_loop._call_llm_with_tools([], tools=[], execution_guard=cancel_guard(state))
    assert calls == ['first']


def test_search_tool_stops_before_wikipedia_or_ddg_fallback(monkeypatch):
    state = {'cancelled': False}
    calls = []

    def fail_first_request(*args, **kwargs):
        calls.append('jina')
        state['cancelled'] = True
        raise OSError('simulated disconnect')

    monkeypatch.setattr(tools.urllib.request, 'urlopen', fail_first_request)
    with pytest.raises(Stopped):
        tools.execute_tool(
            'search_web', {'query': 'offline example'},
            execution_guard=cancel_guard(state),
        )
    assert calls == ['jina']


def test_wikipedia_language_fallback_checks_guard_before_each_http(monkeypatch):
    state = {'cancelled': False}
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            state['cancelled'] = True
            return b'{"query":{"search":[]}}'

    def fake_urlopen(request, **kwargs):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(tools.urllib.request, 'urlopen', fake_urlopen)
    with pytest.raises(Stopped):
        tools._wikipedia_search('example', 5, execution_guard=cancel_guard(state))
    assert len(calls) == 1
    assert calls[0].startswith('https://en.wikipedia.org/')


def test_fetch_webpage_cancellation_after_dns_check_never_starts_http(monkeypatch):
    state = {'cancelled': False}
    calls = []

    def after_dns(url):
        state['cancelled'] = True
        return True, ''

    monkeypatch.setattr(tools, '_is_url_allowed', after_dns)
    monkeypatch.setattr(tools.urllib.request, 'urlopen', lambda *a, **k: calls.append('http'))
    with pytest.raises(Stopped):
        tools.execute_tool(
            'fetch_webpage', {'url': 'https://example.com'},
            execution_guard=cancel_guard(state),
        )
    assert calls == []


def test_semantic_query_variations_stop_before_second_embedding_after_cancellation(monkeypatch):
    state = {'cancelled': False}
    calls = []

    class FakeVectorStore:
        def count(self):
            return 1

        def search(self, query, n):
            calls.append(query)
            state['cancelled'] = True
            return [(1, 0.8)]

    monkeypatch.setattr(
        'api.services.vector_store.VectorStoreService', FakeVectorStore,
    )
    monkeypatch.setattr(
        tools, '_generate_query_variations', lambda query: ['first', 'second'],
    )

    with pytest.raises(Stopped):
        tools.execute_tool(
            'search_news', {'query': 'multi variation research', 'mode': 'semantic'},
            execution_guard=cancel_guard(state),
        )
    assert calls == ['first']
