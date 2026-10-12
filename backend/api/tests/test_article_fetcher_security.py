from __future__ import annotations

import json
import socket
import ssl
from unittest.mock import Mock

import pytest
from django.test import override_settings

from api.services.article_fetcher import core, providers, safe_http
from api.services.article_fetcher.types import FetchError, FetchResult


class StubResponse:
    def __init__(self, body=b'', headers=None):
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class ExternalHackerNewsStory:
    name = 'hackernews_api'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=False,
            provider=self.name,
            url=url,
            error='external_hn_story',
            metadata={'external_url': 'https://private.example/article'},
        )


class RecordingProvider:
    name = 'recording'

    def __init__(self):
        self.urls = []

    def fetch(self, url, expected_title=None, summary=None):
        self.urls.append(url)
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or 'Article',
            markdown='Article\n\n' + ('A real article paragraph. ' * 30),
        )


def _addrinfo(address, port):
    parsed = socket.inet_pton(socket.AF_INET, address)
    assert parsed
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))


def test_production_open_url_routes_to_safe_transport_and_ignores_supplied_context(monkeypatch):
    request = providers.urllib.request.Request('https://example.test/article')
    result = object()
    safe_open = Mock(return_value=result)

    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError('production must not use urllib urlopen')

    monkeypatch.setattr(providers, 'safe_urlopen', safe_open)
    monkeypatch.setattr(providers.urllib.request, 'urlopen', forbidden_urlopen)

    with override_settings(DJANGO_ENV='production'):
        actual = providers._open_url(request, timeout=9, context=object())

    assert actual is result
    safe_open.assert_called_once_with(request, timeout=9)


def test_development_open_url_preserves_existing_urllib_mock_contract(monkeypatch):
    request = providers.urllib.request.Request('https://example.test/article')
    context = ssl.create_default_context()
    result = object()
    urlopen = Mock(return_value=result)
    monkeypatch.setattr(providers.urllib.request, 'urlopen', urlopen)

    with override_settings(DJANGO_ENV='development'):
        actual = providers._open_url(request, timeout=7, context=context)

    assert actual is result
    urlopen.assert_called_once_with(request, timeout=7, context=context)


def test_all_production_direct_providers_share_safe_transport(monkeypatch):
    urls = []

    def safe_open(request, timeout):
        url = request.full_url
        urls.append(url)
        if 'firebaseio.com' in url:
            body = json.dumps({'id': 123, 'url': 'https://example.test/article'}).encode()
            headers = {'content-type': 'application/json'}
        else:
            body = b'# README\nA fetched body.'
            headers = {'content-type': 'text/plain; charset=utf-8'}
        return StubResponse(body, headers)

    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError('production direct fetch escaped the safe helper')

    monkeypatch.setattr(providers, 'safe_urlopen', safe_open)
    monkeypatch.setattr(providers.urllib.request, 'urlopen', forbidden_urlopen)

    with override_settings(DJANGO_ENV='production'):
        providers.GitHubReadmeProvider()._download('https://raw.githubusercontent.com/org/repo/HEAD/README.md')
        providers.HackerNewsAPIProvider().fetch('https://news.ycombinator.com/item?id=123')
        providers.LeiphoneFeedProvider()._download()
        providers.ScrapyHTTPProvider()._download('https://example.test/article')

    assert urls == [
        'https://raw.githubusercontent.com/org/repo/HEAD/README.md',
        'https://hacker-news.firebaseio.com/v0/item/123.json',
        'https://www.leiphone.com/feed',
        'https://example.test/article',
    ]


def test_production_disables_jina_and_subprocess_before_any_external_action(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('unsafe provider performed an external action')

    monkeypatch.setattr(providers.subprocess, 'run', forbidden)
    monkeypatch.setattr(providers.urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(providers, 'safe_urlopen', forbidden)

    with override_settings(DJANGO_ENV='production'):
        jina = providers.JinaProvider().fetch('https://example.test/article')
        scrapy = providers.ScrapySubprocessProvider().fetch('https://example.test/article')
        names = [provider.name for provider in providers.default_providers()]

    assert jina.ok is False and jina.error == 'unsafe_transport_disabled'
    assert scrapy.ok is False and scrapy.error == 'unsafe_transport_disabled'
    assert 'jina' not in names
    assert 'scrapy_subprocess' not in names
    assert {'hackernews_api', 'github_readme', 'leiphone_feed', 'scrapy_http'} <= set(names)


def test_production_core_rejects_invalid_initial_url_before_provider(monkeypatch):
    class MustNotRun:
        name = 'must_not_run'

        def fetch(self, *args, **kwargs):
            raise AssertionError('provider was called for an invalid production URL')

    with override_settings(DJANGO_ENV='production'):
        with pytest.raises(FetchError) as raised:
            core.fetch_article_markdown('http://10.0.0.2/private', providers=[MustNotRun()])

    assert raised.value.failures[0].provider == 'safe_http'
    assert raised.value.failures[0].error == 'Private or local URLs are not allowed'


def test_production_core_validates_hackernews_external_target_before_next_provider(monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        address = '10.2.3.4' if host == 'private.example' else '93.184.216.34'
        return [_addrinfo(address, port)]

    monkeypatch.setattr(safe_http.socket, 'getaddrinfo', fake_getaddrinfo)
    monkeypatch.setattr(
        safe_http.socket,
        'socket',
        lambda *args, **kwargs: pytest.fail('core validation must not connect'),
    )
    recorder = RecordingProvider()

    with override_settings(DJANGO_ENV='production'):
        with pytest.raises(FetchError) as raised:
            core.fetch_article_markdown(
                'https://news.ycombinator.com/item?id=123',
                expected_title='External article',
                providers=[ExternalHackerNewsStory(), recorder],
            )

    assert recorder.urls == []
    assert any(failure.error == 'Private or local URLs are not allowed' for failure in raised.value.failures)
