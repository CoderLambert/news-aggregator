"""Feed admission is server-owned; these synthetic tests are not live evidence."""
from dataclasses import replace
import re
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from api.models import Category, ChannelSubscription, SourceConfig, SourceEndpoint
from api.rss.control_worker import ControlWorker
from api.rss.directory_models import FeedDirectoryEntry, FeedDirectorySnapshot
from api.rss.discovery import discovery_operation_result
from api.rss.feed_policy import (approved_feed_policy, assert_binding_policy,
    known_feed_content_kind, required_entry_url_block_rules)
from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
from api.rss.operations import OperationError, change_policy, enqueue_operation
from api.rss.subscriptions import subscribe
from api.services.source_policy import POLICIES
from api.tests.rss.test_control_worker import (CONFIG, INSTANCE, URL, FakeEngine,
    drain, setup_article, setup_binding)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user(settings, monkeypatch):
    settings.RSS_FULL_CONTENT_ENABLED = True
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', INSTANCE)
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    return get_user_model().objects.create_user('feed-policy-user')


@pytest.fixture
def worker(settings):
    settings.RSS_FULL_CONTENT_ENABLED = True
    engine = FakeEngine()
    worker = ControlWorker(CONFIG, adapter_factory=lambda: engine)
    yield worker, engine
    worker.close()


def selected(user, url, selector):
    if selector == 'feed_url':
        return {'feed_url': url}
    if selector == 'candidate_token':
        op = FeedOperation.objects.create(actor=user, kind='discover', dedupe_key=uuid.uuid4().hex,
            request_hash='a' * 64, state='succeeded', safe_result={'candidates': [{'url': url, 'title': 'WebKit'}]})
        return {'candidate_token': discovery_operation_result(op, user)['candidates'][0]['candidate_token']}
    snapshot = FeedDirectorySnapshot.objects.create(checksum=uuid.uuid4().hex * 2,
        commit='synthetic', license='CC0-1.0', schema_version=1, active=True)
    entry = FeedDirectoryEntry.objects.create(snapshot=snapshot, entry_id=uuid.uuid4(),
        name='Completely unrelated display name', public_url=url, kind='feed')
    return {'directory_entry_id': str(entry.entry_id)}


@pytest.mark.parametrize('selector', ['feed_url', 'candidate_token', 'directory_entry_id'])
@pytest.mark.parametrize('url,mode,reading', [
    ('https://publisher.example/summary.xml', 'full_content', 'standard'),
    ('https://webkit.org/feed/', 'feed', 'public_feed'),
    ('https://jvns.ca/atom.xml', 'feed', 'public_feed'),
    ('https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL', 'feed', 'rss_summary_only'),
    ('https://www.windpowermonthly.com/rss/news', 'feed', 'rss_summary_only'),
    ('https://news.ycombinator.com/rss', 'feed', 'rss_summary_only'),
    ('https://hnrss.org/frontpage', 'feed', 'rss_summary_only'),
    ('https://www.producthunt.com/feed', 'feed', 'rss_summary_only'),
])
def test_all_subscription_selectors_choose_identical_server_policy(user, worker, selector, url, mode, reading):
    control, engine = worker
    status, result = subscribe(user, selected(user, url, selector), 'subscribe')
    assert status == 202
    binding = FeedBinding.objects.get()
    assert binding.desired_mode == mode
    publication = SourcePublication.objects.get(source_id=result['subscription']['source_id'])
    assert publication.reading_policy == reading
    drain(control)
    assert engine.create_calls == 1
    assert engine.feeds[7].crawler is (mode == 'full_content')


@pytest.mark.parametrize('selector', ['feed_url', 'candidate_token', 'directory_entry_id'])
@pytest.mark.parametrize('url', ['https://www.reuters.com/rss', 'https://feeds.reuters.com/news',
                              'https://meta.ai.meta.com/feed', 'https://www.leiphone.com/feed'])
def test_retired_publishers_cannot_bypass_with_token_or_random_catalog_name(user, selector, url):
    with pytest.raises(OperationError, match='source_collection_not_permitted'):
        subscribe(user, selected(user, url, selector), 'subscribe')
    assert FeedBinding.objects.count() == ChannelSubscription.objects.count() == 0


def test_body_fields_are_not_native_evidence_and_exact_path_is_not_host_grant(settings):
    settings.RSS_FULL_CONTENT_ENABLED = True
    assert POLICIES['v8'].body_fields
    assert approved_feed_policy('https://v8.dev/blog.atom').desired_mode == 'full_content'
    assert approved_feed_policy('https://webkit.org/different.xml').desired_mode == 'full_content'
    assert approved_feed_policy('https://webkit.org/feed/?tag=x').desired_mode == 'full_content'


def test_global_opt_out_and_existing_admin_mode_endpoint(user, settings, worker):
    settings.RSS_DEFAULT_FEED_MODE = 'feed'
    subscribe(user, {'feed_url': URL}, 'subscribe')
    binding = FeedBinding.objects.get()
    assert binding.desired_mode == 'feed'
    change_policy(binding.pk, expected_policy_version=binding.policy_version, desired_mode='full_content', actor=user)
    drain(worker[0])
    binding.refresh_from_db()
    assert binding.desired_mode == 'full_content'
    assert worker[1].feeds[7].crawler


@pytest.mark.parametrize('url', ['https://www.windpowermonthly.com/rss/news',
    'https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL', 'https://hnrss.org/frontpage'])
def test_admin_cannot_enable_forbidden_full_content(user, url):
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    subscribe(user, {'feed_url': url}, 'subscribe')
    binding = FeedBinding.objects.get()
    version = binding.policy_version
    with pytest.raises(OperationError, match='full_content_policy_not_permitted'):
        change_policy(binding.pk, expected_policy_version=version, desired_mode='full_content', actor=user)
    binding.refresh_from_db()
    assert binding.policy_version == version and binding.desired_mode == 'feed'


@pytest.mark.parametrize('where', ['prepare', 'dispatch'])
@pytest.mark.parametrize('kind', ['register', 'refresh_feed', 'refetch_entry', 'update_feed_policy'])
def test_publication_tightening_before_send_prevents_engine_api(worker, kind, where):
    control, engine = worker
    actor, binding, source, news, entry = setup_article(engine)
    if kind == 'register':
        FeedBinding.objects.filter(pk=binding.pk).update(engine_feed_id=None, applied_policy_version=0, connection_state='pending')
        binding.refresh_from_db()
    operation = enqueue_operation(kind, actor=actor, binding=binding, dedupe_key='unsafe',
        **({'entry': entry, 'source_id': source.pk} if kind == 'refetch_entry' else {}))
    claim = control.claim_next()
    request = control.prepare(claim) if where == 'dispatch' else None
    SourcePublication.objects.filter(source=source).update(reading_policy='rss_summary_only', policy_version=2)
    request = control._dispatch_or_finish(request) if request else control._prepare_or_finish(claim)
    assert request is None
    operation.refresh_from_db()
    assert operation.state == 'cancelled'
    assert engine.create_calls == engine.policy_calls == engine.refresh_calls == engine.refetch_calls == 0
    assert not connection.in_atomic_block


def config_for(source, *, key='dynamic_restricted', status='enabled', html=False, reading='public_feed'):
    config = SourceConfig.objects.create(source_key=key, source=source,
        publisher_name='Synthetic', channel_name='Unrelated name',
        category=Category.objects.create(name='Policy', slug='policy'), status=status,
        reading_policy=reading, official_html_full_content_allowed=html,
        approved_config_version=1, approved_at=timezone.now())
    SourceEndpoint.objects.create(source_config=config, kind='rss', url=URL,
        allowed_domains=['publisher.example'])
    return config


def test_linked_config_html_disabled_blocks_even_standard_publication(worker):
    actor, binding, source = setup_binding(full=True)
    config_for(source)
    with pytest.raises(OperationError, match='full_content_policy_not_permitted'):
        change_policy(binding.pk, expected_policy_version=1, desired_mode='full_content', actor=actor)
    enqueue_operation('register', actor=actor, binding=binding, dedupe_key='queued')
    drain(worker[0])
    assert worker[1].create_calls == 0


def test_known_url_config_cannot_be_bypassed_by_new_personal_source(user):
    _, _, source = setup_binding()
    config_for(source, key='devto', reading='summary_only')  # built-in key does not hide the DB restriction.
    SourceFeedLink.objects.all().delete()
    FeedBinding.objects.all().delete()
    subscribe(user, {'feed_url': URL}, 'new')
    binding = FeedBinding.objects.get()
    assert binding.desired_mode == 'feed'
    assert SourcePublication.objects.get(source_id=ChannelSubscription.objects.get(user=user).source_id).reading_policy == 'rss_summary_only'


def test_policy_tightening_from_html_allowed_to_false_after_prepare(worker):
    actor, binding, source = setup_binding(full=True)
    config = config_for(source, html=True)
    enqueue_operation('register', actor=actor, binding=binding, dedupe_key='queued')
    request = worker[0].prepare(worker[0].claim_next())
    SourceConfig.objects.filter(pk=config.pk).update(official_html_full_content_allowed=False, config_version=2)
    assert worker[0]._dispatch_or_finish(request) is None
    assert worker[1].create_calls == 0


def test_shared_feed_takes_intersection_of_every_link(worker):
    actor, binding, source = setup_binding(full=True)
    from api.models import Source
    restricted = Source.objects.create(name='Random', url='https://publisher.example')
    SourcePublication.objects.create(source=restricted, owner='miniflux', reading_policy='summary_only')
    SourceFeedLink.objects.create(source=restricted, binding=binding, enabled=False)
    with pytest.raises(OperationError, match='full_content_policy_not_permitted'):
        assert_binding_policy(binding)


def test_stopping_retired_collector_is_always_allowed(worker, monkeypatch):
    actor, binding, source, _, _ = setup_article(worker[1])
    ChannelSubscription.objects.filter(source=source).delete()
    monkeypatch.setitem(POLICIES, 'temporary_denied', replace(POLICIES['reuters'], domains=('publisher.example',)))
    from api.rss.operations import reconcile_binding
    reconcile_binding(binding.pk)
    drain(worker[0])
    assert worker[1].feeds[7].disabled


def test_explicit_repair_checks_target_publisher_not_only_feed(worker):
    actor, binding, source, news, entry = setup_article(worker[1])
    from api.models import News
    News.objects.filter(pk=news.pk).update(url='https://www.reuters.com/restricted-story')
    entry.source_url = 'https://www.reuters.com/restricted-story'
    entry.save(update_fields=['source_url'])
    with pytest.raises(OperationError, match='source_collection_not_permitted'):
        enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
            source_id=source.pk, dedupe_key='no')
    assert worker[1].refetch_calls == 0


def test_http_article_identity_remains_repairable(worker):
    actor, binding, source, news, entry = setup_article(worker[1])
    from api.models import News
    target = 'http://publisher.example/article'
    News.objects.filter(pk=news.pk).update(url=target)
    entry.source_url = target
    entry.save(update_fields=['source_url'])
    worker[1].entry = replace(worker[1].entry, url=target)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='http-article')
    drain(worker[0])
    operation.refresh_from_db()
    assert operation.state == 'succeeded' and worker[1].refetch_calls == 1


def test_remote_refetch_url_change_is_refused_before_fetch_content(worker):
    actor, binding, source, news, entry = setup_article(worker[1])
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='changed-remotely')
    worker[1].entry = replace(worker[1].entry, url='https://www.reuters.com/changed')
    drain(worker[0])
    operation.refresh_from_db()
    assert operation.state == 'cancelled' and operation.safe_result['code'] == 'stale_fence'
    assert worker[1].refetch_calls == 0


def test_dynamic_allowed_domains_restrict_article_urls_not_only_feed_endpoint(worker):
    _, _, source = setup_binding()
    config_for(source)
    from api.rss.feed_policy import assert_article_fetch_allowed
    with pytest.raises(OperationError, match='full_content_policy_not_permitted'):
        assert_article_fetch_allowed('http://publisher.example/other-article')


def test_global_gate_defaults_off_and_admin_cannot_bypass(user, settings, worker):
    settings.RSS_FULL_CONTENT_ENABLED = False
    status, _ = subscribe(user, {'feed_url': URL}, 'closed')
    binding = FeedBinding.objects.get()
    assert status == 202 and binding.desired_mode == 'feed'
    assert not CONFIG.__class__(INSTANCE, 3, 'http://engine:8080', 'synthetic').full_content_enabled
    with pytest.raises(OperationError, match='full_content_disabled'):
        change_policy(binding.pk, expected_policy_version=binding.policy_version, desired_mode='full_content')
    drain(worker[0])
    assert not worker[1].feeds[7].crawler


def test_gate_closing_blocks_preexisting_full_but_permits_stop_and_downgrade(worker, settings):
    actor, binding, source, _, entry = setup_article(worker[1])
    settings.RSS_FULL_CONTENT_ENABLED = False
    with pytest.raises(OperationError, match='full_content_disabled'):
        enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
            source_id=source.pk, dedupe_key='closed')
    operation = enqueue_operation('refresh_feed', actor=actor, binding=binding, dedupe_key='closed-refresh')
    drain(worker[0])
    operation.refresh_from_db()
    assert operation.state == 'cancelled' and worker[1].refresh_calls == 0
    change_policy(binding.pk, expected_policy_version=binding.policy_version, desired_mode='feed')
    drain(worker[0])
    assert not worker[1].feeds[7].crawler


@pytest.mark.parametrize('target', ['https://www.arxiv.org/paper', 'http://x.arxiv.org/paper',
    'https://www.publisher.example/story', 'http://sub.publisher.example/story'])
def test_explicit_repairs_use_same_restrictive_subdomain_rules_as_native_filter(worker, target):
    _, _, source = setup_binding()
    config_for(source)
    from api.rss.feed_policy import assert_article_fetch_allowed
    with pytest.raises(OperationError, match='full_content_policy_not_permitted'):
        assert_article_fetch_allowed(target)


@pytest.mark.parametrize('target,blocked', [
    ('https://www.reuters.com/story', True), ('http://REUTERS.COM.:8080/story', True),
    ('https://news.reuters.com/story', True), ('https://user:pass@reuters.com/story', True),
    ('https://evilreuters.com/story', False), ('https://reuters.com.evil.example/story', False),
    ('https://allowed.example/reuters.com/story', False),
    ('https://reuters.com@allowed.example/story', False),
])
def test_entryurl_rule_authority_boundaries(target, blocked):
    pattern = required_entry_url_block_rules().removeprefix('EntryURL=')
    assert bool(re.search(pattern, target)) == blocked


def test_feed_mode_keeps_permitted_abstract_and_discussion_but_not_retired_publisher():
    base = required_entry_url_block_rules().removeprefix('EntryURL=')
    full = required_entry_url_block_rules(include_html=True).removeprefix('EntryURL=')
    for target in ['https://arxiv.org/abs/1', 'https://news.ycombinator.com/item?id=1', 'https://github.com/a/b']:
        assert not re.search(base, target) and re.search(full, target)
    assert re.search(base, 'https://www.reuters.com/story')


def test_blocked_config_disabled_endpoint_does_not_erase_global_deny(worker):
    _, _, source = setup_binding()
    config = config_for(source, status='blocked')
    SourceEndpoint.objects.filter(source_config=config).update(enabled=False)
    pattern = required_entry_url_block_rules(include_database=True).removeprefix('EntryURL=')
    assert re.search(pattern, 'https://sub.publisher.example/story')


def test_content_kind_metadata_does_not_run_admission_or_full_gate(settings):
    settings.RSS_FULL_CONTENT_ENABLED = 'invalid-on-purpose'
    assert known_feed_content_kind('https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL') == 'abstract'
    assert known_feed_content_kind('https://rss.arxiv.org/atom/math') == 'abstract'
    assert known_feed_content_kind('https://news.ycombinator.com/rss') == 'discussion'
    assert known_feed_content_kind('https://www.reuters.com/rss') == 'article'
