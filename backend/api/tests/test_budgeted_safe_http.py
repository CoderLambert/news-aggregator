"""Transport + real budget integration; socket/DNS only are synthetic."""
from datetime import timedelta
import urllib.error
import urllib.request

import pytest
from django.utils import timezone

from api.models import RequestBudget
from api.services import request_budget as budget
from api.services.article_fetcher import safe_http, core
from api.services.article_fetcher.execution import execution_scope, ExecutionStopped
from api.services.article_fetcher.types import FetchResult, FetchError
from api.tests.test_safe_http import FakeNetwork, _response


@pytest.mark.django_db
def test_429_persists_origin_cooldown_and_reader_cannot_bypass(monkeypatch):
    network = FakeNetwork(monkeypatch, [_response(429, 'Retry-After: 120\r\nContent-Length: 0\r\n')])
    with pytest.raises(urllib.error.HTTPError) as error:
        safe_http.safe_urlopen('http://publisher.example/article')
    assert error.value.error_code == 'rate_limited'
    assert error.value.retry_after_at >= timezone.now() + timedelta(seconds=119)
    assert error.value.http_status == 429
    with pytest.raises(budget.BudgetDeferred):
        safe_http.safe_urlopen('http://r.jina.ai/http://publisher.example/article')
    assert len(network.sockets) == 1
    assert RequestBudget.objects.get(pk='host:publisher.example').cooldown_until is not None
    assert not RequestBudget.objects.exclude(lease_token='').exists()


@pytest.mark.django_db
def test_all_redirect_hops_charge_and_release_own_permits(monkeypatch):
    now = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: now)
    def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
    monkeypatch.setattr(safe_http.time, 'sleep', advance)
    network = FakeNetwork(monkeypatch, [
        _response(302, 'Location: /final\r\nContent-Length: 0\r\n'),
        _response(200, 'Content-Length: 2\r\n', 'ok'),
    ])
    with execution_scope() as context:
        result = safe_http.safe_urlopen('http://publisher.example/start')
        assert result.read() == b'ok'
        assert context.physical_requests == 2
    assert len(network.sockets) == 2 and all(s.closed for s in network.sockets)
    assert not RequestBudget.objects.exclude(lease_token='').exists()


@pytest.mark.django_db
def test_fifth_request_can_finish_but_nested_calls_cannot_reset_counter(monkeypatch):
    now = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: now)
    def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
    monkeypatch.setattr(safe_http.time, 'sleep', advance)
    network = FakeNetwork(monkeypatch, [_response(200, 'Content-Length: 2\r\n', 'ok')] * 5)
    with execution_scope() as context:
        for _ in range(5):
            assert safe_http.safe_urlopen('http://publisher.example/article').read() == b'ok'
        with pytest.raises(ExecutionStopped):
            safe_http.safe_urlopen('http://publisher.example/article')
        assert context.physical_requests == 5
    assert len(network.sockets) == 5
    assert not RequestBudget.objects.exclude(lease_token='').exists()


def test_typed_429_terminates_provider_chain_before_reader():
    calls = []
    class Origin:
        name = 'origin'
        def fetch(self, *args, **kwargs):
            calls.append('origin')
            return FetchResult(False, self.name, error_code='rate_limited', http_status=429,
                               retry_after_at=timezone.now() + timedelta(seconds=60), retryable=True)
    class Reader:
        name = 'reader'
        def fetch(self, *args, **kwargs):
            calls.append('reader')
            raise AssertionError('429 must stop fallback')
    with pytest.raises(FetchError) as error:
        core.fetch_article_markdown('https://dev.to/team/article', providers=[Origin(), Reader()])
    assert calls == ['origin'] and error.value.error_code == 'rate_limited'


def test_budget_deferred_propagates_through_provider_catch_all(monkeypatch):
    from api.services.article_fetcher.providers import ScrapyHTTPProvider
    deferred = budget.BudgetDeferred(timezone.now() + timedelta(seconds=60), ['host:dev.to'])
    def fail(*args, **kwargs):
        raise deferred
    monkeypatch.setattr(ScrapyHTTPProvider, '_download', fail)
    with pytest.raises(budget.BudgetDeferred) as error:
        core.fetch_article_markdown('https://dev.to/team/article', providers=[ScrapyHTTPProvider()])
    assert error.value is deferred


@pytest.mark.django_db
def test_oversized_compressed_429_still_commits_cooldown_from_headers(monkeypatch):
    network = FakeNetwork(monkeypatch, [_response(429, 'Retry-After: 120\r\nContent-Encoding: gzip\r\nContent-Length: 99999999\r\n')])
    with pytest.raises(urllib.error.HTTPError) as error:
        safe_http.safe_urlopen('http://publisher.example/article')
    assert error.value.error_code == 'rate_limited'
    assert RequestBudget.objects.get(pk='host:publisher.example').cooldown_until >= timezone.now() + timedelta(seconds=119)
    assert network.sockets[0].closed


def test_invalid_typed_candidate_is_a_validation_failure_without_mutating_frozen_result():
    from api.services.article_fetcher.types import FullContentCandidate
    candidate = FullContentCandidate('devto', '17', 'https://dev.to/team/article', 'https://dev.to/api/articles/17',
                                     None, 'Title', 'article', 'body_markdown', 'markdown', 'partial',
                                     'Incomplete body.', None, None, timezone.now())
    class Provider:
        name = 'devto'
        def fetch(self, *args, **kwargs):
            return FetchResult(True, self.name, candidate=candidate)
    with pytest.raises(FetchError) as error:
        core.fetch_article_markdown(candidate.target_url, providers=[Provider()])
    assert error.value.error_code == 'body_partial'


@pytest.mark.django_db
def test_reader_redirect_keeps_logical_origin_scope(monkeypatch):
    now = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: now)
    def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
    monkeypatch.setattr(safe_http.time, 'sleep', advance)
    network = FakeNetwork(monkeypatch, [
        _response(302, 'Location: http://reader-cdn.example/result\r\nContent-Length: 0\r\n'),
        _response(429, 'Retry-After: 120\r\nContent-Length: 0\r\n'),
    ])
    with pytest.raises(urllib.error.HTTPError):
        safe_http.safe_urlopen(urllib.request.Request('http://r.jina.ai/http://publisher.example/article', headers={'Authorization': 'Bearer synthetic'}))
    assert len(network.sockets) == 2
    assert RequestBudget.objects.get(pk='host:publisher.example').cooldown_until >= now + timedelta(seconds=120)
    assert RequestBudget.objects.get(pk='host:r.jina.ai').cooldown_until >= now + timedelta(seconds=120)
    assert RequestBudget.objects.filter(pk__startswith='credential:jina:', cooldown_until__isnull=False).count() == 1
    assert b'Authorization:' not in network.sockets[1].sent
    assert not RequestBudget.objects.exclude(lease_token='').exists()


def test_deterministic_capacity_and_identity_failures_are_not_retried():
    from api.services.article_fetcher.types import transport_failure
    for message in ('HTTP response exceeds size limit', 'Private or local URLs are not allowed'):
        result = transport_failure(safe_http.UnsafeURL(message), provider='safe_http')
        assert not result.retryable
        assert result.error_code in {'unsupported', 'invalid_identity'}
