"""Synthetic-only normal subscription/create path against the pinned engine."""
from dataclasses import replace
import json
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineAdapter, EngineConfig, EngineError
from api.rss.models import FeedBinding, FeedOperation, SourcePublication
from api.rss.operations import OperationError, change_policy, enqueue_operation
from api.rss.subscriptions import subscribe

call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
config = EngineConfig.from_environment()
assert config.full_content_enabled and settings.RSS_FULL_CONTENT_ENABLED
adapter = EngineAdapter(config)
worker = ControlWorker(config)
user = get_user_model().objects.create_user('synthetic-feed-policy')
BASE = 'https://publisher.example:8443'


def drain():
    for _ in range(40):
        if not worker.run_once():
            return
    raise AssertionError('unbounded pending operations')


def normal_subscribe(path, key):
    status, result = subscribe(user, {'feed_url': BASE + path}, key)
    assert status == 202
    binding = FeedBinding.objects.get(canonical_feed_url=BASE + path)
    drain()
    binding.refresh_from_db()
    assert binding.connection_state == 'ready', list(FeedOperation.objects.values('state', 'safe_result'))
    return binding


ordinary = normal_subscribe('/feed', 'ordinary')
assert ordinary.desired_mode == 'full_content'
assert adapter.get_feed(ordinary.engine_feed_id).crawler
entries = adapter.list_entries(0, adapter.read_upper_bound())
assert [entry.url for entry in entries] == [BASE + '/allowed']
assert len(entries[0].content) > 1000
refresh = enqueue_operation('refresh_feed', actor=user, binding=ordinary, dedupe_key='refresh')
drain()
refresh.refresh_from_db()
assert refresh.state == 'succeeded'

# Global deployment gate: the normal service chooses feed and admin cannot
# override. The SDK independently refuses create(full, disabled=True) as well.
with override_settings(RSS_FULL_CONTENT_ENABLED=False):
    closed_config = replace(config, full_content_enabled=False)
    worker.config = closed_config
    closed = EngineAdapter(closed_config)
    for disabled in (False, True):
        try:
            closed.create_feed(BASE + '/never-created', desired_mode='full_content', disabled=disabled)
        except EngineError as error:
            assert error.code == 'full_content_disabled'
        else:
            raise AssertionError('disabled gate allowed initial crawler')
    try:
        closed.refresh_feed(ordinary.engine_feed_id)
    except EngineError as error:
        assert error.code == 'full_content_disabled'
    else:
        raise AssertionError('disabled gate allowed full refresh')
    try:
        closed.refetch_entry(entries[0].id)
    except EngineError as error:
        assert error.code == 'full_content_disabled'
    else:
        raise AssertionError('disabled gate allowed refetch')
    feed_only = normal_subscribe('/feed-only', 'closed-default')
    assert feed_only.desired_mode == 'feed' and not adapter.get_feed(feed_only.engine_feed_id).crawler
    try:
        change_policy(feed_only.pk, expected_policy_version=feed_only.policy_version,
            desired_mode='full_content', actor=user)
    except OperationError as error:
        assert error.code == 'full_content_disabled'
    else:
        raise AssertionError('admin bypassed global gate')
    change_policy(ordinary.pk, expected_policy_version=ordinary.policy_version, desired_mode='feed')
    drain()
    assert not adapter.get_feed(ordinary.engine_feed_id).crawler
    closed.close()
worker.config = config
entries = adapter.list_entries(0, adapter.read_upper_bound())
assert 'https://arxiv.org:8443/abstract' in [entry.url for entry in entries]

# Deliberate negative evidence: Miniflux's entry filter precedes rewriting and
# HTTP redirects, so an allowed URL can redirect to a forbidden publisher. Both
# hosts resolve only to our synthetic fixture and trust only its temporary CA.
redirect = normal_subscribe('/feed-redirect', 'redirect-limitation')
assert adapter.get_feed(redirect.engine_feed_id).crawler
worker.close()
adapter.close()
print(json.dumps({'normal_subscribe_initial_crawler': True, 'initial_extracted_body': True,
    'direct_forbidden_entries_excluded': True, 'feed_only_abstract_preserved': True,
    'gate_off_normal_default_feed': True, 'gate_off_admin_full_refused': True,
    'gate_off_sdk_full_create_refetch_refresh_refused': True, 'gate_off_feed_downgrade_allowed': True,
    'refresh_requested': True, 'redirect_gate': 'BLOCKED: inspect fixture counter negative evidence',
    'scope': 'synthetic publisher only; no public request or production state'}, sort_keys=True))
