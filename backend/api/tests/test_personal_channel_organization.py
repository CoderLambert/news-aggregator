"""Personal organization contracts: synthetic data, no provider or site fixtures."""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Source, News, Category, ChannelSubscription, ChannelGroup, ChannelGroupMember
from api.smart_channel_models import ChannelGroupingConfig, ChannelGroupingProposal, ChannelGroupingOverride, SubscriptionGroupingState, SourceTopicProfile
from api.services.channel_grouping import process_subscription
from api.services.channel_ai import process_incremental_subscriptions, claim_next, execute_job
from api.tests.test_classification_evidence import example


@pytest.fixture(autouse=True)
def isolated_organization_cache():
    # DB test rollback reuses user IDs; throttle counters need the same per-test
    # isolation, without disabling or relaxing the real throttling behavior.
    with override_settings(CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': f'personal-organization-{uuid.uuid4()}',
    }}):
        yield


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
class PersonalOrganizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('personal-organizer')
        self.other = User.objects.create_user('other-organizer')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.source = Source.objects.create(name='React Blog', url='https://react.dev')
        self.group = ChannelGroup.objects.create(user=self.user, name='前端开发')
        self.category = Category.objects.create(name='Test', slug='personal-test')

    def configure(self, **kwargs):
        response = self.client.patch('/api/me/smart-channels/settings/', {'match_existing': True, 'mode': 'auto', **kwargs}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def subscribe(self, source=None):
        return ChannelSubscription.objects.create(user=self.user, source=source or self.source)

    def propose(self, **kwargs):
        return self.client.post('/api/me/smart-channels/proposals/', {'target': 'groups', 'source_ids': [self.source.pk], **kwargs}, format='json')

    def apply(self, proposal, assignments=None):
        return self.client.post(f'/api/me/smart-channels/proposals/{proposal}/apply/', {'assignments': assignments or [{'source_id': self.source.pk, 'group_ids': [self.group.pk]}]}, format='json')

    def bulk(self, action, group=None, sources=None):
        return self.client.post('/api/me/channel-subscriptions/', {'action': action, 'group_id': (group or self.group).pk, 'source_ids': sources or [self.source.pk]}, format='json')

    def test_trusted_name_match_without_bindings_is_automatic_and_idempotent(self):
        self.configure()
        subscription = self.subscribe()
        process_subscription(subscription.pk)
        process_subscription(subscription.pk)
        self.assertTrue(self.group.subscriptions.filter(pk=subscription.pk).exists())
        proposal = ChannelGroupingProposal.objects.get(user=self.user)
        self.assertEqual(proposal.status, 'applied')
        self.assertEqual(proposal.target, 'groups')
        self.assertEqual(proposal.result[0]['group_ids'], [self.group.pk])
        self.assertFalse(SourceTopicProfile.objects.exists())

    def test_partial_setting_save_preserves_activation_and_pending_backlog(self):
        self.configure()
        before = ChannelGroupingConfig.objects.get(user=self.user).active_since
        subscription = self.subscribe()
        self.configure(daily_limit=3)
        cfg = ChannelGroupingConfig.objects.get(user=self.user)
        self.assertEqual(cfg.active_since, before)
        process_incremental_subscriptions()
        self.assertTrue(self.group.subscriptions.filter(pk=subscription.pk).exists())
        self.assertEqual(self.client.get('/api/me/smart-channels/settings/').data['summary']['applied'], 1)

    def test_initial_activation_leaves_old_subscriptions_for_explicit_preview(self):
        subscription = self.subscribe()
        self.configure()
        process_incremental_subscriptions()
        self.assertFalse(self.group.subscriptions.exists())
        proposal = self.propose()
        self.assertEqual(proposal.data.get('target'), 'groups')
        self.assertEqual(self.apply(proposal.data['id']).status_code, 200)
        self.assertTrue(self.group.subscriptions.filter(pk=subscription.pk).exists())

    def test_title_arrival_resumes_pending_but_cannot_authorize_auto_apply(self):
        self.configure()
        unknown = Source.objects.create(name='Independent weekly', url='https://example.test')
        subscription = self.subscribe(unknown)
        process_subscription(subscription.pk)
        self.assertEqual(SubscriptionGroupingState.objects.get(subscription=subscription).status, 'pending')
        for i, title in enumerate(['React server components', 'CSS grid browser rendering', 'TypeScript applications']):
            News.objects.create(source=unknown, category=self.category, title=title, content='summary', url=f'https://example.test/{i}', publish_time=timezone.now())
        process_incremental_subscriptions()
        proposal = ChannelGroupingProposal.objects.get(user=self.user)
        self.assertEqual(proposal.result[0]['group_ids'], [self.group.pk])
        self.assertTrue(proposal.result[0]['needs_review'])
        self.assertFalse(self.group.subscriptions.exists())
        self.assertFalse(SourceTopicProfile.objects.exists())

    def test_group_proposal_rejects_stale_titles_and_group_definition(self):
        self.subscribe()
        proposal = self.propose()
        self.group.name = 'Web'
        self.group.save()
        self.assertEqual(self.apply(proposal.data['id']).status_code, 409)
        proposal = self.propose()
        News.objects.create(source=self.source, category=self.category, title='New title', content='summary', url='https://react.dev/new', publish_time=timezone.now())
        self.assertEqual(self.apply(proposal.data['id']).status_code, 409)
        self.assertFalse(ChannelGroupMember.objects.exists())

    def test_group_assignments_are_owned_unique_and_bounded(self):
        self.subscribe()
        foreign = ChannelGroup.objects.create(user=self.other, name='Private')
        proposal = self.propose().data['id']
        self.assertEqual(self.apply(proposal, [{'source_id': self.source.pk, 'group_ids': [foreign.pk]}]).status_code, 404)
        row = {'source_id': self.source.pk, 'group_ids': [self.group.pk]}
        self.assertEqual(self.apply(proposal, [row, row]).status_code, 400)
        self.assertEqual(self.apply(proposal, [{'source_id': self.source.pk, 'group_ids': [self.group.pk, self.group.pk]}]).status_code, 400)
        self.assertFalse(ChannelGroupMember.objects.exists())
        self.client.force_authenticate(self.other)
        self.assertEqual(self.apply(proposal).status_code, 404)

    def test_move_is_atomic_and_manual_remove_blocks_later_worker(self):
        self.configure()
        subscription = self.subscribe()
        old = ChannelGroup.objects.create(user=self.user, name='Old')
        old.subscriptions.add(subscription)
        self.assertEqual(self.bulk('move_to_group', sources=[self.source.pk, 987654]).status_code, 404)
        self.assertTrue(old.subscriptions.filter(pk=subscription.pk).exists())
        self.assertEqual(self.bulk('move_to_group').status_code, 200)
        self.assertFalse(old.subscriptions.exists())
        self.assertTrue(self.group.subscriptions.filter(pk=subscription.pk).exists())
        self.assertEqual(self.bulk('remove_from_group').status_code, 200)
        process_subscription(subscription.pk)
        self.assertFalse(self.group.subscriptions.exists())
        self.assertTrue(ChannelGroupingOverride.objects.get(user=self.user, group=self.group, source=self.source).suppressed)

    def test_undo_preserves_membership_touched_by_explicit_manual_add(self):
        self.subscribe()
        proposal = self.propose().data['id']
        self.assertEqual(self.apply(proposal).status_code, 200)
        self.assertEqual(self.bulk('add_to_group').status_code, 200)
        response = self.client.post(f'/api/me/smart-channels/proposals/{proposal}/undo/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.group.subscriptions.exists())

    def test_background_ai_requires_explicit_model_and_consent(self):
        response = self.configure()
        self.assertIs(response.data.get('ai_enabled'), False)
        for payload in ({'ai_enabled': True}, {'ai_enabled': True, 'consent': True}, {'daily_limit': True}, {'daily_limit': 21}, {'match_existing': 'yes'}):
            response = self.client.patch('/api/me/smart-channels/settings/', payload, format='json')
            self.assertEqual(response.status_code, 400, payload)


def enable_background(example, daily_limit=2):
    from api.ai_model_models import UserAIModelConfig
    user, source, article = example
    client = APIClient()
    client.force_authenticate(user)
    group = ChannelGroup.objects.create(user=user, name='Personal research picks')
    model = UserAIModelConfig.objects.get(connection__user=user)
    response = client.patch('/api/me/smart-channels/settings/', {'mode': 'auto', 'match_existing': True,
        'ai_enabled': True, 'consent': True, 'model_config_id': str(model.pk), 'daily_limit': daily_limit}, format='json')
    assert response.status_code == 200, response.data
    ChannelSubscription.objects.filter(user=user).update(created_at=timezone.now())
    return client, group


def test_custom_group_ai_proposal_uses_private_ids_and_never_writes_public_profile(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = claim_next()
    assert job is not None, 'opted-in pending subscription must queue a bounded AI job'
    gateway = Mock()
    def completion(**kwargs):
        prompt = json.loads(kwargs['messages'][1]['content'])
        assert prompt['allowed_groups'][0]['group_id'] == group.pk
        assert prompt['allowed_groups'][0]['name'] == 'Personal research picks'
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            tool_calls=None, refusal=None, content=json.dumps({'channels': [{'source_id': example[1].pk, 'group_ids': [group.pk], 'reason': 'Matches saved evidence'}]})))])
    gateway.chat.completions.create.side_effect = completion
    with patch('api.services.channel_ai.build_gateway_client', return_value=gateway):
        execute_job(job)
    job.refresh_from_db()
    assert job.status == 'ready', job.error_code
    assert job.result[0]['group_ids'] == [group.pk] and job.result[0]['needs_review'] is True
    assert not ChannelGroupMember.objects.exists()
    assert not SourceTopicProfile.objects.filter(source=example[1]).exists()


def test_disable_background_while_inflight_fences_result_and_unknown_send_is_not_requeued(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = claim_next()
    assert job is not None
    gateway = Mock()
    def completion(**kwargs):
        response = client.patch('/api/me/smart-channels/settings/', {'ai_enabled': False}, format='json')
        assert response.status_code == 200
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            tool_calls=None, refusal=None, content=json.dumps({'channels': [{'source_id': example[1].pk, 'group_ids': [group.pk], 'reason': 'test'}]})))])
    gateway.chat.completions.create.side_effect = completion
    with patch('api.services.channel_ai.build_gateway_client', return_value=gateway):
        execute_job(job)
    job.refresh_from_db()
    assert job.status in {'failed', 'cancelled'} and job.dispatch_started_at is not None
    assert not ChannelGroupMember.objects.exists()
    assert not any(row.get('origin') == 'ai' for row in job.result)
    from api.ai_model_models import UserAIModelConfig
    model = UserAIModelConfig.objects.get(connection__user=example[0])
    client.patch('/api/me/smart-channels/settings/', {'ai_enabled': True, 'consent': True, 'model_config_id': str(model.pk)}, format='json')
    process_incremental_subscriptions()
    assert claim_next() is None
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 1


def group_response(source_ids, group_id):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
        tool_calls=None, refusal=None, content=json.dumps({'channels': [
            {'source_id': source_id, 'group_ids': [group_id], 'reason': 'Saved evidence'} for source_id in source_ids]})))])


def test_unrelated_import_during_ai_does_not_discard_valid_result(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = claim_next()
    gateway = Mock()
    def completion(**kwargs):
        extra = Source.objects.create(name='Unrelated import', url='https://example.test/unrelated')
        ChannelSubscription.objects.create(user=example[0], source=extra)
        return group_response(job.source_ids, group.pk)
    gateway.chat.completions.create.side_effect = completion
    with patch('api.services.channel_ai.build_gateway_client', return_value=gateway):
        execute_job(job)
    job.refresh_from_db()
    assert job.status == 'ready', job.error_code
    response = client.post(f'/api/me/smart-channels/proposals/{job.pk}/apply/', {
        'assignments': [{'source_id': example[1].pk, 'group_ids': [group.pk]}]}, format='json')
    assert response.status_code == 200, response.data


def test_pending_ai_batches_sources_and_recovers_daily_budget(example):
    client, group = enable_background(example, daily_limit=1)
    additional = []
    for i in range(2):
        source = Source.objects.create(name=f'Batch source {i}', url=f'https://example.test/batch/{i}', description='Saved research description')
        additional.append(source)
        ChannelSubscription.objects.create(user=example[0], source=source)
    process_incremental_subscriptions()
    first = ChannelGroupingProposal.objects.get(engine='ai')
    assert set(first.source_ids) == {example[1].pk, *(s.pk for s in additional)}
    source = Source.objects.create(name='Deferred', url='https://example.test/deferred', description='Saved research description')
    subscription = ChannelSubscription.objects.create(user=example[0], source=source)
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 1
    assert SubscriptionGroupingState.objects.get(subscription=subscription).status == 'pending'
    ChannelGroupingProposal.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=1))
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 2
    assert ChannelGroupingProposal.objects.exclude(pk=first.pk).get().source_ids == [source.pk]


def test_unknown_dispatch_remains_barrier_after_new_title_or_group_change(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = claim_next()
    ChannelGroupingProposal.objects.filter(pk=job.pk).update(dispatch_started_at=timezone.now(), lease_until=timezone.now() - timedelta(seconds=1))
    assert claim_next() is None
    News.objects.filter(pk=example[2].pk).update(title='A different title')
    group.name = 'Changed research group'
    group.save()
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 1
    assert claim_next() is None


def test_known_unsent_failure_has_one_automatic_recovery_not_unbounded_requeue(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    first = ChannelGroupingProposal.objects.get(engine='ai')
    ChannelGroupingProposal.objects.filter(pk=first.pk).update(status='failed', attempts=1)
    # Recovery does not require an unrelated config or evidence edit.
    client.patch('/api/me/smart-channels/settings/', {'daily_limit': 4}, format='json')
    process_incremental_subscriptions()
    second = ChannelGroupingProposal.objects.exclude(pk=first.pk).get()
    ChannelGroupingProposal.objects.filter(pk=second.pk).update(status='failed', attempts=2)
    client.patch('/api/me/smart-channels/settings/', {'daily_limit': 4}, format='json')
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 2


def test_two_owners_progress_under_bounded_round_robin_scan(db, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    owners = [User.objects.create_user(f'fair-owner-{i}') for i in range(2)]
    for user in owners:
        ChannelGroupingConfig.objects.create(user=user, mode='auto', match_existing=True,
            active_since=timezone.now()-timedelta(days=1), personal_active_since=timezone.now()-timedelta(days=1))
        ChannelGroup.objects.create(user=user, name='前端开发')
    unknowns = Source.objects.bulk_create([Source(name=f'Unknown {i}', url=f'https://example.test/{i}') for i in range(5)])
    ChannelSubscription.objects.bulk_create([ChannelSubscription(user=owners[0], source=source) for source in unknowns])
    trusted = Source.objects.create(name='React Blog', url='https://react.dev')
    other = ChannelSubscription.objects.create(user=owners[1], source=trusted)
    for _ in range(2):
        assert process_incremental_subscriptions(limit=1) <= 1
    assert ChannelGroupMember.objects.filter(subscription=other).exists()
    # Progress behind unchanged old pending subscriptions is bounded per tick.
    newcomer = ChannelSubscription.objects.create(user=owners[0], source=trusted)
    for _ in range(12):
        assert process_incremental_subscriptions(limit=1) <= 1
    assert ChannelGroupMember.objects.filter(subscription=newcomer).exists()


def test_unsent_failure_recovers_without_editing_evidence_or_settings(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    first = ChannelGroupingProposal.objects.get(engine='ai')
    ChannelGroupingProposal.objects.filter(pk=first.pk).update(status='failed', attempts=1)
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 2


def test_private_group_examples_have_global_prompt_budget(db):
    from api.services.channel_grouping import private_groups
    user = User.objects.create_user('bounded-examples')
    source = Source.objects.create(name='Example', url='https://example.test', description='x' * 600)
    category = Category.objects.create(name='Bounded', slug='bounded')
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    for i in range(3):
        News.objects.create(source=source, category=category, title='title' * 36, content='summary',
            url=f'https://example.test/title/{i}', publish_time=timezone.now())
    for i in range(40):
        group = ChannelGroup.objects.create(user=user, name=f'Group {i}')
        group.subscriptions.add(subscription)
    context = private_groups(user)
    assert len(context) == 40
    assert len(json.dumps(context, ensure_ascii=False)) < 18000
    assert sum(len(g['examples']) for g in context) <= 20


@pytest.mark.parametrize('change', ['group_name', 'example_title', 'target_subscription'])
def test_changed_private_group_context_during_ai_fails_closed(example, change):
    client, group = enable_background(example)
    example_source = Source.objects.create(name='Existing example', url='https://example.test/old')
    member = ChannelSubscription.objects.create(user=example[0], source=example_source)
    group.subscriptions.add(member)
    article = News.objects.create(source=example_source, category=example[2].category, title='Example title', content='summary',
        url='https://example.test/old-article', publish_time=timezone.now())
    process_incremental_subscriptions()
    job = claim_next()
    assert job is not None
    gateway = Mock()
    def completion(**kwargs):
        if change == 'group_name':
            ChannelGroup.objects.filter(pk=group.pk).update(name='Renamed')
        elif change == 'example_title':
            News.objects.filter(pk=article.pk).update(title='Changed example title')
        else:
            ChannelSubscription.objects.filter(user=example[0], source=example[1]).delete()
        return group_response(job.source_ids, group.pk)
    gateway.chat.completions.create.side_effect = completion
    with patch('api.services.channel_ai.build_gateway_client', return_value=gateway):
        execute_job(job)
    job.refresh_from_db()
    assert job.status == 'failed'
    assert not any(row.get('origin') == 'ai' for row in job.result)


def test_group_output_rejects_cross_owner_boolean_duplicate_and_invented_ids(db):
    from api.services.channel_ai import parse_group_classification
    evidence = [{'source_id': 1, 'name': 'A'}]
    groups = [{'group_id': 2, 'name': 'Owned'}]
    for ids in ([3], [True], [2, 2], [2, 2, 2, 2]):
        with pytest.raises(ValueError):
            parse_group_classification(json.dumps({'channels': [{'source_id': 1, 'group_ids': ids, 'reason': 'test'}]}), evidence, groups)
    with pytest.raises(ValueError):
        parse_group_classification('{"channels":[],"channels":[]}', evidence, groups)


def test_deleted_legacy_binding_cannot_prevent_disabling_background_ai(example):
    client, group = enable_background(example)
    ChannelGroupingConfig.objects.filter(user=example[0]).update(bindings={'ai': group.pk})
    process_incremental_subscriptions()
    job = claim_next()
    assert job is not None
    group.delete()
    response = client.patch('/api/me/smart-channels/settings/', {'ai_enabled': False}, format='json')
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.status == 'cancelled'


@pytest.mark.parametrize('initial', [{'mode': 'off'}, {'mode': 'suggest', 'match_existing': False}])
def test_first_personal_activation_excludes_existing_legacy_backlog(db, settings, initial):
    settings.PUBLIC_SITE_MODE = 'full'
    user = User.objects.create_user('activation')
    client = APIClient()
    client.force_authenticate(user)
    assert client.patch('/api/me/smart-channels/settings/', initial, format='json').status_code == 200
    source = Source.objects.create(name='React Blog', url='https://react.dev')
    old = ChannelSubscription.objects.create(user=user, source=source)
    group = ChannelGroup.objects.create(user=user, name='前端开发')
    assert client.patch('/api/me/smart-channels/settings/', {'mode': 'auto', 'match_existing': True}, format='json').status_code == 200
    process_incremental_subscriptions()
    assert not group.subscriptions.filter(pk=old.pk).exists()
    # Partial saves and disable/re-enable preserve the cutoff and real backlog.
    source2 = Source.objects.create(name='WebKit', url='https://webkit.org')
    new = ChannelSubscription.objects.create(user=user, source=source2)
    for payload in ({'mode': 'off'}, {'daily_limit': 3}, {'mode': 'auto'}):
        assert client.patch('/api/me/smart-channels/settings/', payload, format='json').status_code == 200
    process_incremental_subscriptions()
    assert group.subscriptions.filter(pk=new.pk).exists()
    assert not group.subscriptions.filter(pk=old.pk).exists()


def test_oversized_owner_defers_observably_without_blocking_other_owners_or_jobs(db, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    users = [User.objects.create_user(f'group-limit-{i}') for i in range(2)]
    for user in users:
        client = APIClient()
        client.force_authenticate(user)
        assert client.patch('/api/me/smart-channels/settings/', {'mode': 'auto', 'match_existing': True}, format='json').status_code == 200
    ChannelGroup.objects.bulk_create([ChannelGroup(user=users[0], name=f'Excess {i}') for i in range(201)])
    normal_group = ChannelGroup.objects.create(user=users[1], name='前端开发')
    source = Source.objects.create(name='React Blog', url='https://react.dev')
    for user in users:
        ChannelSubscription.objects.create(user=user, source=source)
    queued = ChannelGroupingProposal.objects.create(user=users[1], engine='ai', status='queued', execution_snapshot={'schema_version': 1},
        input_snapshot='', source_ids=[source.pk], expires_at=timezone.now()+timedelta(hours=1))
    process_incremental_subscriptions()
    assert normal_group.subscriptions.filter(source=source).exists()
    assert claim_next().pk == queued.pk
    client.force_authenticate(users[0])
    assert client.get('/api/me/smart-channels/settings/').data['error_code'] == 'too_many_groups'


def _deferral_pair(prefix):
    """Two activated owners with one pending subscription each."""
    users = [User.objects.create_user(f'{prefix}-{i}') for i in range(2)]
    for user in users:
        ChannelGroupingConfig.objects.create(user=user, mode='auto', match_existing=True,
            active_since=timezone.now() - timedelta(days=1), personal_active_since=timezone.now() - timedelta(days=1))
        ChannelGroup.objects.create(user=user, name='前端开发')
    failing = ChannelSubscription.objects.create(user=users[0], source=Source.objects.create(name='React Blog', url='https://react.dev'))
    other = ChannelSubscription.objects.create(user=users[1], source=Source.objects.create(name='WebKit', url='https://webkit.org'))
    return users, failing, other


def test_owner_scoped_failure_defers_only_that_owner(db, settings):
    """A rejected owner (404/409/429-style) must not stop other owners' work."""
    from rest_framework.exceptions import NotFound
    settings.PUBLIC_SITE_MODE = 'full'
    users, failing, other = _deferral_pair('defer')

    def dispatch(pk, **kwargs):
        if pk == failing.pk:
            raise NotFound('只能整理自己的已订阅频道。')
        return process_subscription(pk, **kwargs)

    with patch('api.services.channel_ai.process_subscription', side_effect=dispatch):
        assert process_incremental_subscriptions() == 1
    assert ChannelGroupMember.objects.filter(subscription=other).exists()
    assert not ChannelGroupMember.objects.filter(subscription=failing).exists()
    deferred = ChannelGroupingConfig.objects.get(user=users[0])
    assert deferred.last_error_code == 'organization_deferred'
    assert deferred.last_scanned_at is not None
    # The deferred owner is retried once its own data is valid again.
    process_incremental_subscriptions()
    assert ChannelGroupMember.objects.filter(subscription=failing).exists()


def test_unexpected_owner_failure_rotates_instead_of_holding_the_front_slot(db, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    users, failing, other = _deferral_pair('rotate')
    state = {'raised': False}

    def boom(pk, **kwargs):
        if pk == failing.pk and not state['raised']:
            state['raised'] = True
            raise RuntimeError('synthetic internal failure in one owner')
        return process_subscription(pk, **kwargs)

    with patch('api.services.channel_ai.process_subscription', side_effect=boom):
        with pytest.raises(RuntimeError):
            process_incremental_subscriptions()
    # The bug stays visible, but the failing owner no longer holds the front slot.
    assert ChannelGroupingConfig.objects.get(user=users[0]).last_scanned_at is not None
    process_incremental_subscriptions()
    assert ChannelGroupMember.objects.filter(subscription=other).exists()
    assert ChannelGroupMember.objects.filter(subscription=failing).exists()


def test_history_pagination_reaches_older_pending_and_preserves_owner_target(db, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    owner = User.objects.create_user('history-owner')
    other = User.objects.create_user('history-other')
    client = APIClient()
    client.force_authenticate(owner)
    for i in range(40):
        ChannelGroupingProposal.objects.create(user=owner, target='groups', status='ready', input_snapshot='', expires_at=timezone.now()+timedelta(days=1))
    ChannelGroupingProposal.objects.create(user=owner, target='topics', status='applied', input_snapshot='', expires_at=timezone.now()+timedelta(days=1))
    ChannelGroupingProposal.objects.create(user=other, target='groups', status='ready', input_snapshot='', expires_at=timezone.now()+timedelta(days=1))
    first = client.get('/api/me/smart-channels/proposals/?target=groups&page=1')
    second = client.get('/api/me/smart-channels/proposals/?target=groups&page=2')
    assert first.status_code == second.status_code == 200
    rows = first.data['results'] + second.data['results']
    assert len(first.data['results']) == 30 and len(second.data['results']) == 10
    assert len({item['id'] for item in rows}) == 40
    assert all(item['target'] == 'groups' for item in rows)
    assert first.data['count'] == 40 and second.data['count'] == 40
    assert first.data['page'] == 1 and second.data['page'] == 2
    assert first.data['page_size'] == second.data['page_size'] == 30
    assert first.data['has_more'] is True and second.data['has_more'] is False
    for query in ('page=0', 'page=-1', 'page=true', 'page=10001', 'target=private', 'target='):
        assert client.get('/api/me/smart-channels/proposals/?'+query).status_code == 400


@pytest.mark.parametrize('total,expected', [(0, (0, False)), (29, (29, False)), (30, (30, False)), (31, (30, True)), (40, (30, True))])
def test_history_pagination_contract_reports_count_and_has_more(db, settings, total, expected):
    """A full page is not the same as another page: `has_more` decides it."""
    settings.PUBLIC_SITE_MODE = 'full'
    user = User.objects.create_user(f'history-count-{total}')
    client = APIClient()
    client.force_authenticate(user)
    for _ in range(total):
        ChannelGroupingProposal.objects.create(user=user, target='groups', status='ready', input_snapshot='', expires_at=timezone.now()+timedelta(days=1))
    response = client.get('/api/me/smart-channels/proposals/?page=1')
    assert response.status_code == 200
    # Pinned for the frontend `ProposalPage` type: renaming a key is a contract change.
    assert set(response.data) == {'results', 'page', 'page_size', 'count', 'has_more'}
    assert (len(response.data['results']), response.data['has_more']) == expected
    assert response.data['count'] == total and response.data['page_size'] == 30
    # The page size is a server contract; a client cannot widen or shrink it.
    widened = client.get('/api/me/smart-channels/proposals/?page=1&page_size=1&limit=1')
    assert widened.data['page_size'] == 30 and len(widened.data['results']) == min(30, total)
    # Pages past the end stay well-formed instead of erroring or repeating rows.
    beyond = client.get('/api/me/smart-channels/proposals/?page=3')
    assert beyond.status_code == 200 and beyond.data['results'] == []
    assert beyond.data['count'] == total and beyond.data['has_more'] is False


def test_history_pagination_is_stable_for_identical_timestamps(db, settings):
    """Ties are broken deterministically, so paging never duplicates or skips a record."""
    settings.PUBLIC_SITE_MODE = 'full'
    user = User.objects.create_user('history-ties')
    client = APIClient()
    client.force_authenticate(user)
    stamp = timezone.now() - timedelta(minutes=5)
    created = [ChannelGroupingProposal.objects.create(user=user, target='groups', status='ready', input_snapshot='',
        expires_at=timezone.now()+timedelta(days=1)) for _ in range(35)]
    ChannelGroupingProposal.objects.filter(pk__in=[item.pk for item in created]).update(created_at=stamp)

    def page_ids(number):
        response = client.get(f'/api/me/smart-channels/proposals/?page={number}')
        assert response.status_code == 200
        return [item['id'] for item in response.data['results']], response.data

    first, first_meta = page_ids(1)
    second, second_meta = page_ids(2)
    assert len(first) == 30 and len(second) == 5
    assert first_meta['has_more'] is True and second_meta['has_more'] is False
    assert len(set(first + second)) == 35, 'identical timestamps must not repeat or drop records'
    assert (page_ids(1)[0], page_ids(2)[0]) == (first, second), 'the same page is stable across requests'



def test_explicit_cancel_is_not_automatically_undone_by_unsent_recovery(example):
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = ChannelGroupingProposal.objects.get(engine='ai')
    assert client.post(f'/api/me/smart-channels/proposals/{job.pk}/cancel/', {}, format='json').status_code == 200
    process_incremental_subscriptions()
    assert claim_next() is None
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 1


@pytest.mark.parametrize('payload', [{'mode': 'off'}, {'ai_enabled': False}])
def test_revoked_model_does_not_prevent_stopping_background(example, payload):
    from django.db.models import F
    from api.ai_connection_models import UserAIConnection
    client, group = enable_background(example)
    process_incremental_subscriptions()
    job = ChannelGroupingProposal.objects.get(engine='ai')
    UserAIConnection.objects.filter(user=example[0]).update(is_enabled=False, credential_epoch=F('credential_epoch')+1)
    response = client.patch('/api/me/smart-channels/settings/', payload, format='json')
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.status == 'cancelled'
    client.patch('/api/me/smart-channels/settings/', {'mode': 'auto'}, format='json')
    process_incremental_subscriptions()
    assert claim_next() is None
    assert ChannelGroupingProposal.objects.filter(engine='ai').count() == 1


@pytest.mark.parametrize('legacy_mode', ['suggest', 'auto'])
def test_legacy_config_anchors_cutoff_instead_of_legacy_active_since(db, settings, legacy_mode):
    """A topics-era config must not organize its existing backlog on first personal use."""
    settings.PUBLIC_SITE_MODE = 'full'
    user = User.objects.create_user(f'legacy-cutoff-{legacy_mode}')
    group = ChannelGroup.objects.create(user=user, name='前端开发')
    source = Source.objects.create(name='React Blog', url='https://react.dev')
    old = ChannelSubscription.objects.create(user=user, source=source)
    ChannelSubscription.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    cfg = ChannelGroupingConfig.objects.create(user=user, mode=legacy_mode, match_existing=True,
        active_since=timezone.now() - timedelta(days=90))
    assert cfg.personal_active_since is None, 'forward migration leaves the legacy row without a cutoff'
    started = timezone.now()
    process_incremental_subscriptions()
    cfg.refresh_from_db()
    assert not group.subscriptions.filter(pk=old.pk).exists()
    assert cfg.personal_active_since is not None and cfg.personal_active_since >= started
    assert cfg.personal_active_since > cfg.active_since, 'the legacy topics cutoff is never reused'
    # The anchored cutoff is a real boundary: newer subscriptions still organize.
    fresh = ChannelSubscription.objects.create(user=user, source=Source.objects.create(name='WebKit', url='https://webkit.org'))
    process_incremental_subscriptions()
    if legacy_mode == 'auto':
        assert group.subscriptions.filter(pk=fresh.pk).exists()
    else:
        proposal = ChannelGroupingProposal.objects.get(target='groups')
        assert proposal.source_ids == [fresh.source_id]
        assert not group.subscriptions.exists()
    assert not group.subscriptions.filter(pk=old.pk).exists()


def test_new_subscription_anchors_legacy_cutoff_without_being_skipped(db, settings):
    """The first personal event anchors the cutoff at that subscription, not after it."""
    settings.PUBLIC_SITE_MODE = 'full'
    user = User.objects.create_user('legacy-event')
    group = ChannelGroup.objects.create(user=user, name='前端开发')
    old_source = Source.objects.create(name='React Blog', url='https://react.dev')
    old = ChannelSubscription.objects.create(user=user, source=old_source)
    ChannelSubscription.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    ChannelGroupingConfig.objects.create(user=user, mode='auto', match_existing=True,
        active_since=timezone.now() - timedelta(days=90))
    event = ChannelSubscription.objects.create(user=user, source=Source.objects.create(name='WebKit', url='https://webkit.org'))
    process_subscription(event.pk)
    cfg = ChannelGroupingConfig.objects.get(user=user)
    assert cfg.personal_active_since is not None and cfg.personal_active_since <= event.created_at
    assert group.subscriptions.filter(pk=event.pk).exists()
    assert not group.subscriptions.filter(pk=old.pk).exists()
    # A later worker tick keeps both decisions.
    process_incremental_subscriptions()
    assert group.subscriptions.filter(pk=event.pk).exists()
    assert not group.subscriptions.filter(pk=old.pk).exists()


def test_legacy_ai_config_does_not_enqueue_pre_activation_backlog(example):
    user, source, _ = example
    client, group = enable_background(example)
    ChannelGroupingConfig.objects.filter(user=user).update(personal_active_since=None,
        active_since=timezone.now() - timedelta(days=90))
    ChannelSubscription.objects.filter(user=user).update(created_at=timezone.now() - timedelta(days=30))
    process_incremental_subscriptions()
    assert not ChannelGroupingProposal.objects.filter(engine='ai').exists()
    cfg = ChannelGroupingConfig.objects.get(user=user)
    assert cfg.personal_active_since is not None
    # Only subscriptions created after the anchored cutoff are queued for AI.
    ChannelSubscription.objects.filter(user=user).update(created_at=timezone.now())
    process_incremental_subscriptions()
    assert ChannelGroupingProposal.objects.filter(engine='ai').exists()


def test_forward_migration_preserves_legacy_config_proposal_and_membership(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    script = """
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
old = [('api', '0083_rss_import_scheduling')]
new = [('api', '0084_personal_channel_organization')]
executor = MigrationExecutor(connection)
executor.migrate(old)
apps = executor.loader.project_state(old).apps
user = apps.get_model('auth', 'User').objects.create(username='legacy-preserved')
source = apps.get_model('api', 'Source').objects.create(name='Legacy preserved', url='https://example.test')
subscription = apps.get_model('api', 'ChannelSubscription').objects.create(user_id=user.pk, source_id=source.pk)
group = apps.get_model('api', 'ChannelGroup').objects.create(user_id=user.pk, name='My custom name')
member = apps.get_model('api', 'ChannelGroupMember').objects.create(group_id=group.pk, subscription_id=subscription.pk)
config = apps.get_model('api', 'ChannelGroupingConfig').objects.create(user_id=user.pk, mode='auto', bindings={'frontend': group.pk}, revision=7)
proposal = apps.get_model('api', 'ChannelGroupingProposal').objects.create(user_id=user.pk, source_ids=[source.pk], topic_keys=['frontend'], input_snapshot='legacy-snapshot', expires_at=timezone.now())
executor = MigrationExecutor(connection)
executor.migrate(new)
apps = executor.loader.project_state(new).apps
current = apps.get_model('api', 'ChannelGroupingConfig').objects.get(pk=config.pk)
assert current.mode == 'auto' and current.revision == 7 and current.bindings == {'frontend': group.pk}
assert current.active_since == config.active_since and current.personal_active_since is None
assert current.ai_enabled is False and current.match_existing is False and current.execution_snapshot == {}
current_proposal = apps.get_model('api', 'ChannelGroupingProposal').objects.get(pk=proposal.pk)
assert current_proposal.target == 'topics' and current_proposal.input_snapshot == 'legacy-snapshot'
assert current_proposal.source_ids == [source.pk] and current_proposal.topic_keys == ['frontend']
assert apps.get_model('api', 'ChannelGroupMember').objects.filter(pk=member.pk, subscription_id=subscription.pk, group_id=group.pk).exists()
connection.close()
"""
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_DB_PATH': str(tmp_path / 'upgrade.sqlite3'), 'RUN_MAIN': 'true'}
    result = subprocess.run([sys.executable, '-c', script], cwd=root, env=environment,
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
