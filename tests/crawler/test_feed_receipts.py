"""Feed validators acknowledge committed items, including fault boundaries.

All publisher inputs and Pipeline results are synthetic. Database tests use
pytest's isolated SQLite database; no publisher HTTP is performed.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone
from scrapy.exceptions import DropItem

from api.models import FeedState
from api.services.feed_state import prepare_feed_request
from api.services.news_ingestion import IngestResult
from news_crawler import feed_receipts, pipelines
from news_crawler.feed_receipts import FeedReceipt, FeedReceiptRegistry
from news_crawler.spiders import feed as feed_module
from news_crawler.spiders.feed import FeedSpider


def receipt(registry, *, entries=1, enumerated=True, context=None):
    result = registry.add(FeedReceipt(
        context or object(), entries, '"new-etag"',
        'Tue, 13 Oct 2026 01:00:00 GMT', 'https://webkit.org/feed/',
    ))
    result.enumerated = enumerated
    return result


@pytest.fixture
def checkpoint_calls(monkeypatch):
    commit = Mock(return_value=True)
    defer = Mock(return_value=True)
    monkeypatch.setattr(feed_receipts, 'commit_feed_checkpoint', commit)
    monkeypatch.setattr(feed_receipts, 'defer_feed', defer)
    return commit, defer


@pytest.mark.parametrize('terminal', ['missing', 'failed', 'deferred'])
def test_incomplete_or_unsuccessful_entry_never_acknowledges_response(terminal, checkpoint_calls):
    commit, defer = checkpoint_calls
    registry = FeedReceiptRegistry()
    response = receipt(registry, entries=2)
    registry.settle(response.token(0), 'committed')
    if terminal != 'missing':
        registry.settle(response.token(1), terminal, 'persistence_conflict')

    totals = registry.finish('finished')

    commit.assert_not_called()
    defer.assert_called_once_with(response.context)
    assert not totals['checkpoint_committed']
    assert totals['entries_committed'] == 1
    assert totals['persistence_failures'] == 1
    assert totals['outcome'] == 'partial'


def test_incomplete_enumeration_blocks_checkpoint_even_with_all_known_items_committed(checkpoint_calls):
    commit, defer = checkpoint_calls
    registry = FeedReceiptRegistry()
    response = receipt(registry, enumerated=False)
    registry.settle(response.token(0), 'committed')

    assert not registry.finish('finished')['checkpoint_committed']
    commit.assert_not_called()
    defer.assert_called_once_with(response.context)


@pytest.mark.parametrize('reason', ['cancelled', 'shutdown', 'closespider_itemcount'])
def test_abnormal_close_preserves_checkpoint_after_every_item_committed(reason, checkpoint_calls):
    commit, defer = checkpoint_calls
    registry = FeedReceiptRegistry()
    response = receipt(registry)
    registry.settle(response.token(0), 'committed')

    totals = registry.finish(reason)

    commit.assert_not_called()
    defer.assert_called_once_with(response.context)
    assert not totals['checkpoint_committed']
    assert totals['outcome'] == 'partial'


def test_commits_and_explicit_policy_skips_acknowledge_complete_response(checkpoint_calls):
    commit, defer = checkpoint_calls
    registry = FeedReceiptRegistry()
    response = receipt(registry, entries=3)
    registry.settle(response.token(0), 'committed', changed=True, body_committed=True)
    registry.settle(response.token(1), 'committed')  # Idempotent replay.
    registry.settle(response.token(2), 'policy_skip', 'older_window')

    totals = registry.finish('finished')

    commit.assert_called_once_with(response.context, etag=response.etag,
                                   last_modified=response.last_modified,
                                   effective_url=response.effective_url)
    defer.assert_not_called()
    assert totals == {
        'entries_seen': 3, 'entries_committed': 2, 'entries_changed': 1,
        'body_candidates_committed': 1, 'policy_skips_by_reason': {'older_window': 1},
        'parse_failures': 0, 'persistence_failures': 0,
        'checkpoint_committed': True, 'outcome': 'updated',
    }


def test_idempotent_replay_can_commit_checkpoint_without_reporting_changed(checkpoint_calls):
    registry = FeedReceiptRegistry()
    response = receipt(registry)
    registry.settle(response.token(0), 'committed', changed=False)

    totals = registry.finish('finished')

    assert totals['checkpoint_committed']
    assert totals['outcome'] == 'unchanged'
    assert totals['entries_changed'] == 0


@pytest.mark.parametrize('enumerated', [False, True])
def test_only_completely_enumerated_empty_feed_is_valid_empty(enumerated, checkpoint_calls):
    commit, defer = checkpoint_calls
    registry = FeedReceiptRegistry()
    response = receipt(registry, entries=0, enumerated=enumerated)

    totals = registry.finish('finished')

    assert totals['checkpoint_committed'] is enumerated
    assert totals['outcome'] == ('valid_empty' if enumerated else 'partial')
    assert commit.call_count == int(enumerated)
    assert defer.call_count == int(not enumerated)
    assert totals['entries_seen'] == 0


def test_checkpoint_cas_loss_is_deferred_and_does_not_fall_back_to_unconditional_write(checkpoint_calls):
    commit, defer = checkpoint_calls
    commit.return_value = False
    registry = FeedReceiptRegistry()
    response = receipt(registry)
    registry.settle(response.token(0), 'committed')

    totals = registry.finish('finished')

    assert totals['outcome'] == 'deferred'
    assert not totals['checkpoint_committed']
    assert totals['entries_committed'] == 1
    commit.assert_called_once()
    defer.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('failure', ['missing', 'failed', 'deferred', 'cancelled', 'cas_lost'])
def test_failure_keeps_persisted_validator_and_other_runs_progress(failure):
    context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    previous_success = timezone.now()
    FeedState.objects.filter(pk=context.state_id).update(
        etag='"previous"', last_modified='previous-modified',
        last_success_at=previous_success, validated_effective_url=context.request_url,
    )
    registry = FeedReceiptRegistry()
    response = receipt(registry, context=context)
    if failure == 'cas_lost':
        FeedState.objects.filter(pk=context.state_id).update(
            revision=context.expected_revision + 1, etag='"other-run"',
            last_modified='other-run-modified',
        )
    if failure in {'failed', 'deferred'}:
        registry.settle(response.token(0), failure)
    elif failure in {'cancelled', 'cas_lost'}:
        registry.settle(response.token(0), 'committed')

    totals = registry.finish('cancelled' if failure == 'cancelled' else 'finished')

    state = FeedState.objects.get(pk=context.state_id)
    assert not totals['checkpoint_committed']
    assert state.etag == ('"other-run"' if failure == 'cas_lost' else '"previous"')
    assert state.last_modified == ('other-run-modified' if failure == 'cas_lost' else 'previous-modified')
    assert state.last_success_at == previous_success
    assert state.revision == context.expected_revision + int(failure == 'cas_lost')


@pytest.mark.django_db
def test_empty_receipt_persists_validators_and_advances_revision():
    context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    registry = FeedReceiptRegistry()
    response = receipt(registry, entries=0, context=context)

    totals = registry.finish('finished')

    state = FeedState.objects.get(pk=context.state_id)
    assert totals['outcome'] == 'valid_empty'
    assert totals['checkpoint_committed']
    assert state.etag == response.etag
    assert state.last_modified == response.last_modified
    assert state.last_success_at is not None
    assert state.revision == context.expected_revision + 1
    assert state.next_poll_at > state.last_success_at


def spider_and_item():
    spider = FeedSpider(name='webkit')
    spider.feed_receipts = FeedReceiptRegistry()
    spider.feed_errors = 0
    spider.feed_outcomes = []
    spider.crawler = SimpleNamespace(stats=SimpleNamespace(set_value=Mock()))
    response = receipt(spider.feed_receipts)
    return spider, response, {'feed_receipt_id': response.token(0)}


def test_scraped_error_and_drop_signals_cannot_overwrite_deferred(checkpoint_calls):
    commit, _ = checkpoint_calls
    spider, response, item = spider_and_item()
    spider.feed_receipts.settle(item['feed_receipt_id'], 'deferred', 'persistence_conflict')

    spider._item_scraped(item)
    spider._item_error(item)
    dropped = DropItem('older_window')
    dropped.ingest_result = IngestResult(None, 'policy_skip', 'older_window')
    spider._item_dropped(item, dropped)

    totals = spider.feed_receipts.finish('finished')
    assert response.terminal[0][:2] == ('deferred', 'persistence_conflict')
    assert totals['persistence_failures'] == 1
    assert totals['entries_committed'] == 0
    assert totals['policy_skips_by_reason'] == {}
    commit.assert_not_called()


def test_item_scraped_without_committed_result_is_contract_failure(checkpoint_calls):
    commit, _ = checkpoint_calls
    spider, response, item = spider_and_item()

    spider._item_scraped(item)

    assert response.terminal[0][:2] == ('failed', 'unsettled_item')
    assert not spider.feed_receipts.finish('finished')['checkpoint_committed']
    commit.assert_not_called()


def test_unknown_drop_is_failed_not_policy_skip(checkpoint_calls):
    commit, _ = checkpoint_calls
    spider, response, item = spider_and_item()

    spider._item_dropped(item, DropItem('opaque error'))

    assert response.terminal[0][:2] == ('failed', 'unclassified_drop')
    assert spider.feed_receipts.finish('finished')['policy_skips_by_reason'] == {}
    commit.assert_not_called()


@pytest.mark.parametrize('outcome', ['committed', 'policy_skip', 'deferred'])
def test_pipeline_uses_explicit_persisted_result_instead_of_success_signal(outcome, monkeypatch, checkpoint_calls):
    spider, response, item = spider_and_item()
    result = IngestResult(31, outcome, 'explicit_reason', changed=True, body_committed=True)

    async def save(data):
        assert asyncio.current_task() in spider.feed_receipts.active_pipeline_tasks
        assert data['source_key'] == 'webkit'
        return SimpleNamespace(_ingest_result=result)

    monkeypatch.setattr(pipelines, '_save_item', save)
    returned = asyncio.run(pipelines.DjangoPipeline().process_item(item, spider))
    spider._item_scraped(item)

    assert returned is item
    assert response.terminal[0] == (outcome, 'explicit_reason', True, True)
    assert not spider.feed_receipts.active_pipeline_tasks
    assert spider.feed_receipts.finish('finished')['checkpoint_committed'] is (outcome != 'deferred')


@pytest.mark.parametrize('kind', ['unknown', 'deferred', 'policy_skip', 'cancelled'])
def test_pipeline_exception_preserves_classification_and_removes_active_task(kind, monkeypatch, checkpoint_calls):
    spider, response, item = spider_and_item()
    error = asyncio.CancelledError() if kind == 'cancelled' else RuntimeError('save failed')
    if kind in {'deferred', 'policy_skip'}:
        error.ingest_result = IngestResult(None, kind, 'explicit_failure')

    async def save(data):
        assert asyncio.current_task() in spider.feed_receipts.active_pipeline_tasks
        raise error

    monkeypatch.setattr(pipelines, '_save_item', save)
    with pytest.raises(type(error)) as raised:
        asyncio.run(pipelines.DjangoPipeline().process_item(item, spider))

    assert raised.value is error
    expected = kind if kind in {'deferred', 'policy_skip'} else 'failed'
    assert response.terminal[0][:2] == (expected, 'explicit_failure' if hasattr(error, 'ingest_result') else 'pipeline_error')
    assert not spider.feed_receipts.active_pipeline_tasks
    assert spider.feed_receipts.finish('finished')['checkpoint_committed'] is (kind == 'policy_skip')


def test_close_waits_for_running_pipeline_before_checkpoint(monkeypatch, checkpoint_calls):
    commit, _ = checkpoint_calls
    spider, response, item = spider_and_item()

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def save(data):
            entered.set()
            await release.wait()
            return SimpleNamespace(_ingest_result=IngestResult(31, 'committed', changed=True))

        async def database(function, *args, **kwargs):
            return function(*args, **kwargs)

        monkeypatch.setattr(pipelines, '_save_item', save)
        monkeypatch.setattr(feed_module, '_database', database)
        running = asyncio.create_task(pipelines.DjangoPipeline().process_item(item, spider))
        await entered.wait()
        closing = asyncio.create_task(spider._feed_closed('finished'))
        await asyncio.sleep(0)
        assert not closing.done()
        commit.assert_not_called()
        assert not response.complete
        release.set()
        await asyncio.gather(running, closing)

    asyncio.run(exercise())
    commit.assert_called_once()
    assert not spider.feed_receipts.active_pipeline_tasks
    spider.crawler.stats.set_value.assert_any_call('checkpoint_committed', True)


def test_cancelled_pipeline_close_never_commits_checkpoint(monkeypatch, checkpoint_calls):
    commit, _ = checkpoint_calls
    spider, response, item = spider_and_item()

    async def exercise():
        entered = asyncio.Event()

        async def save(data):
            entered.set()
            await asyncio.Event().wait()

        async def database(function, *args, **kwargs):
            return function(*args, **kwargs)

        monkeypatch.setattr(pipelines, '_save_item', save)
        monkeypatch.setattr(feed_module, '_database', database)
        running = asyncio.create_task(pipelines.DjangoPipeline().process_item(item, spider))
        await entered.wait()
        closing = asyncio.create_task(spider._feed_closed('finished'))
        await asyncio.sleep(0)
        running.cancel()
        await asyncio.gather(running, closing, return_exceptions=True)

    asyncio.run(exercise())
    assert response.terminal[0][0] == 'failed'
    assert not spider.feed_receipts.active_pipeline_tasks
    commit.assert_not_called()
    spider.crawler.stats.set_value.assert_any_call('checkpoint_committed', False)


@pytest.mark.parametrize('outcome,exception_type', [('deferred', RuntimeError), ('policy_skip', DropItem)])
def test_sync_save_exposes_ingest_result_on_rejection(outcome, exception_type, monkeypatch):
    import api.services.news_ingestion as ingestion
    result = IngestResult(None, outcome, 'persistence_conflict' if outcome == 'deferred' else 'invalid_identity')
    monkeypatch.setattr(pipelines, 'close_old_connections', Mock())
    monkeypatch.setattr(ingestion, 'ingest_item', Mock(return_value=result))

    with pytest.raises(exception_type) as caught:
        pipelines._save_item_sync({'source_name': 'WebKit'})

    assert caught.value.ingest_result is result
    assert str(caught.value) == result.reason


def test_not_due_feed_reports_healthy_skip_without_network_or_checkpoint(monkeypatch):
    """A recently checked feed must not turn the scheduler batch red."""
    from datetime import timedelta
    from types import SimpleNamespace
    from unittest.mock import Mock
    from api.services.crawl_metrics import crawl_result, describe_crawl_result

    spider = FeedSpider(name='webkit')
    spider.feed_receipts = FeedReceiptRegistry()
    spider.feed_outcomes = []
    spider.feed_errors = 0
    stats = {}
    spider.crawler = SimpleNamespace(stats=SimpleNamespace(set_value=lambda key, value: stats.__setitem__(key, value)))
    future = timezone.now() + timedelta(minutes=20)
    state = SimpleNamespace(next_poll_at=future, request_url='https://webkit.org/feed/', headers=())

    async def fake_db(function, *args, **kwargs):
        if function is feed_module.prepare_feed_request:
            return state
        return function(*args, **kwargs)

    monkeypatch.setattr(feed_module, '_database', fake_db)

    async def crawl():
        return [request async for request in spider.start()]

    assert asyncio.run(crawl()) == []
    asyncio.run(spider._feed_closed('finished'))
    assert stats['outcome'] == 'not_due'
    assert stats['checkpoint_committed'] is False
    assert stats['next_attempt_at'] == future.isoformat()
    summary = crawl_result({'finish_reason': 'finished', **stats})
    assert summary['outcome'] == 'not_due'
    assert summary['failure_outcome'] == ''
    assert '未请求源站' in describe_crawl_result(summary)
    assert summary['physical_requests'] == 0


def test_not_due_does_not_turn_a_real_failed_ingest_into_success(monkeypatch, checkpoint_calls):
    from datetime import timedelta
    spider, response, item = spider_and_item()
    spider.feed_outcomes.append('not_due')
    spider.feed_receipts.settle(item['feed_receipt_id'], 'deferred', 'persistence_conflict')
    totals = spider.feed_receipts.finish('finished')
    assert totals['outcome'] == 'partial'
    assert not totals['checkpoint_committed']
