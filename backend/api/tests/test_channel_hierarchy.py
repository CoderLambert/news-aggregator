import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import ChannelGroup, ChannelGroupRoot, ChannelSubscription, Source
from api.services.channel_ai import (
    _run_guard, enqueue_personal_batch, parse_group_classification, parse_hierarchy,
)
from api.services.channel_grouping import (
    GroupingConflict, apply_proposal, hierarchy_state, make_proposal, private_groups,
    process_subscription, snapshot, undo_proposal,
)
from api.services.channel_topics import digest, evidence_for
from api.smart_channel_models import (
    ChannelGroupingConfig, ChannelGroupingProposal, SourceTopicProfile,
    SubscriptionGroupingState,
)

pytestmark = pytest.mark.django_db


def taxonomy():
    return {
        'schema_version': 2,
        'roots': [
            {'root_id': 1, 'name': '工程', 'version': 1},
            {'root_id': 2, 'name': '产品', 'version': 1},
        ],
        'children': [
            {'group_id': 10, 'root_id': 1, 'name': '后端', 'version': 1, 'source_ids': []},
            {'group_id': 11, 'root_id': 1, 'name': '前端', 'version': 1, 'source_ids': []},
        ],
        'selected_source_ids': [], 'evidence_hashes': [], 'config': {}, 'overrides': [],
    }


def test_hierarchy_parser_normalizes_owned_roots_and_rejects_unsafe_results():
    state = taxonomy()
    parsed = parse_hierarchy(json.dumps({'hierarchy': [
        {'root_id': None, 'root_name': ' 工程 ', 'group_ids': [10], 'reason': '保持工程方向'},
        {'root_id': None, 'root_name': '行业', 'group_ids': [11], 'reason': '形成宽主题'},
    ]}, ensure_ascii=False), state)
    assert parsed == [
        {'root_id': 1, 'root_name': None, 'group_ids': [10], 'reason': '保持工程方向'},
        {'root_id': None, 'root_name': '行业', 'group_ids': [11], 'reason': '形成宽主题'},
    ]
    invalid = [
        {'hierarchy': [{'root_id': True, 'root_name': None, 'group_ids': [10, 11], 'reason': 'x'}]},
        {'hierarchy': [{'root_id': 999, 'root_name': None, 'group_ids': [10, 11], 'reason': 'x'}]},
        {'hierarchy': [{'root_id': 1, 'root_name': None, 'group_ids': [10, 10], 'reason': 'x'}]},
        {'hierarchy': [{'root_id': None, 'root_name': 'bad\u0000', 'group_ids': [10, 11], 'reason': 'x'}]},
        {'hierarchy': [{'root_id': 1, 'root_name': None, 'group_ids': [10], 'reason': 'x', 'extra': 1}]},
    ]
    for payload in invalid:
        with pytest.raises(ValueError):
            parse_hierarchy(json.dumps(payload), state)


def hierarchy_example():
    user = User.objects.create_user('hierarchy-owner')
    first_root = ChannelGroupRoot.objects.create(user=user, name='已有分组')
    destination = ChannelGroupRoot.objects.create(user=user, name='技术')
    first = ChannelGroup.objects.create(user=user, root=first_root, name='前端')
    second = ChannelGroup.objects.create(user=user, root=first_root, name='商业')
    source = Source.objects.create(name='Hierarchy evidence', url='https://example.test/hierarchy-evidence')
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    first.subscriptions.add(subscription)
    second.subscriptions.add(subscription)
    return user, first_root, destination, first, second, subscription


def ready_proposal(user, result):
    state = hierarchy_state(user)
    source_ids = state['selected_source_ids']
    return ChannelGroupingProposal.objects.create(
        user=user, engine='ai', target='hierarchy', status='ready',
        source_ids=source_ids, topic_keys=[], group_snapshot=state,
        input_snapshot=digest(state), evidence=[
            evidence_for(source) for source in Source.objects.filter(pk__in=source_ids).order_by('pk')
        ], result=result, expires_at=timezone.now() + timedelta(hours=1),
    )


def test_hierarchy_apply_is_atomic_idempotent_and_cas_undo_reports_skips():
    user, original, destination, first, second, subscription = hierarchy_example()
    rows = [
        {'root_id': destination.pk, 'root_name': None, 'group_ids': [first.pk], 'reason': '技术归并'},
        {'root_id': None, 'root_name': '行业', 'group_ids': [second.pk], 'reason': '行业归并'},
    ]
    proposal = ready_proposal(user, rows)
    applied = apply_proposal(user, proposal.pk, {'rows': rows})
    assert applied.status == 'applied'
    assert len(applied.applied_changes) == 2
    first.refresh_from_db(); second.refresh_from_db()
    created = ChannelGroupRoot.objects.get(user=user, name='行业')
    assert first.root_id == destination.pk and second.root_id == created.pk
    assert set(first.subscriptions.values_list('pk', flat=True)) == {subscription.pk}
    assert set(second.subscriptions.values_list('pk', flat=True)) == {subscription.pk}
    assert apply_proposal(user, proposal.pk, {'rows': rows}).applied_changes == applied.applied_changes
    assert ChannelGroupRoot.objects.filter(user=user, name='行业').count() == 1

    second.root = destination
    second.version += 1
    second.save(update_fields=['root', 'version', 'updated_at'])
    undone = undo_proposal(user, proposal.pk)
    first.refresh_from_db(); second.refresh_from_db()
    assert first.root_id == original.pk
    assert second.root_id == destination.pk
    assert ChannelGroupRoot.objects.filter(pk=created.pk).exists()
    assert [change['undo_status'] for change in undone.applied_changes] == ['restored', 'skipped']
    assert undo_proposal(user, proposal.pk).status == 'undone'


def test_hierarchy_snapshot_stales_on_structure_membership_and_evidence_but_not_unrelated_subscription():
    user, _, destination, first, _, subscription = hierarchy_example()
    row = {'root_id': destination.pk, 'root_name': None, 'group_ids': [first.pk], 'reason': 'move'}
    unchanged = ready_proposal(user, [row])
    unrelated = Source.objects.create(name='Ungrouped', url='https://example.test/ungrouped')
    ChannelSubscription.objects.create(user=user, source=unrelated)
    assert snapshot(user, unchanged.source_ids, 'hierarchy') == unchanged.input_snapshot

    membership = ready_proposal(user, [row])
    grouped_source = Source.objects.create(name='New member', url='https://example.test/new-member')
    first.subscriptions.add(ChannelSubscription.objects.create(user=user, source=grouped_source))
    with pytest.raises(GroupingConflict):
        apply_proposal(user, membership.pk, {'rows': [row]})

    evidence = ready_proposal(user, [row])
    source = subscription.source
    source.description = 'Changed after preview'
    source.save(update_fields=['description'])
    with pytest.raises(GroupingConflict):
        apply_proposal(user, evidence.pk, {'rows': [row]})

    structure = ready_proposal(user, [row])
    first.name = '人工改名'
    first.version += 1
    first.save(update_fields=['name', 'version', 'updated_at'])
    with pytest.raises(GroupingConflict):
        apply_proposal(user, structure.pk, {'rows': [row]})


def test_hierarchy_creation_requires_consent_allows_only_one_active_and_worker_fences_changes(settings):
    settings.PUBLIC_AI_ENABLED = True
    user, _, _, first, _, _ = hierarchy_example()
    payload = {
        'target': 'hierarchy', 'engine': 'ai', 'request_id': str(uuid.uuid4()),
        'model_config_id': 'synthetic-model',
    }
    with patch('api.services.channel_grouping.credential_fingerprint', return_value='fingerprint'), \
            patch('api.services.channel_model.capture_model', return_value={'model': {'model_id': 'synthetic'}}):
        with pytest.raises(ValidationError):
            make_proposal(user, payload)
        proposal = make_proposal(user, {**payload, 'consent': True})
        assert proposal.status == 'queued'
        assert proposal.group_snapshot['schema_version'] == 2
        with pytest.raises(GroupingConflict):
            make_proposal(user, {**payload, 'request_id': str(uuid.uuid4()), 'consent': True})

    proposal.status = 'running'
    proposal.lease_token = 'lease'
    proposal.lease_until = timezone.now() + timedelta(minutes=1)
    proposal.save(update_fields=['status', 'lease_token', 'lease_until'])
    first.name = 'Changed after dispatch'
    first.version += 1
    first.save(update_fields=['name', 'version', 'updated_at'])
    with patch('api.services.channel_ai.permitted', return_value=True):
        with pytest.raises(ValueError, match='configuration_changed'):
            _run_guard(proposal)


def test_channel_parser_and_apply_create_first_reviewed_root_child_path_without_early_write():
    user = User.objects.create_user('first-path-owner')
    source = Source.objects.create(name='First path source', url='https://example.test/first-path')
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    context = private_groups(user)
    evidence = [evidence_for(source)]
    raw = json.dumps({'channels': [{
        'source_id': source.pk, 'group_ids': [],
        'new_group_paths': [{
            'root_id': None, 'root_name': '工程', 'name': '后端',
        }],
        'reason': '根据频道工程内容',
    }]}, ensure_ascii=False)
    result = parse_group_classification(raw, evidence, context, allow_new_paths=True)
    assert result[0]['new_group_paths'] == [{
        'root_id': None, 'root_name': '工程', 'name': '后端',
    }]
    assert not ChannelGroupRoot.objects.filter(user=user).exists()
    assert not ChannelGroup.objects.filter(user=user).exists()

    proposal = ChannelGroupingProposal.objects.create(
        user=user, engine='ai', target='groups', status='ready',
        source_ids=[source.pk], topic_keys=[], group_snapshot=context,
        input_snapshot=snapshot(user, [source.pk], 'groups'),
        evidence=evidence, result=result,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    assignment = {
        'source_id': source.pk, 'group_ids': [],
        'new_group_paths': result[0]['new_group_paths'],
    }
    apply_proposal(user, proposal.pk, {'assignments': [assignment]})
    root = ChannelGroupRoot.objects.get(user=user, name='工程')
    child = ChannelGroup.objects.get(user=user, root=root, name='后端')
    assert child.subscriptions.get() == subscription
    undo_proposal(user, proposal.pk)
    assert ChannelGroupRoot.objects.filter(pk=root.pk).exists()
    assert ChannelGroup.objects.filter(pk=child.pk).exists()
    assert not child.subscriptions.exists()


def test_background_ai_can_queue_a_review_only_first_path(settings):
    settings.PUBLIC_AI_ENABLED = True
    user = User.objects.create_user('background-first-path')
    source = Source.objects.create(
        name='Background source', url='https://example.test/background-path',
        description='Engineering articles for grouping',
    )
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    ChannelGroupingConfig.objects.create(
        user=user, mode='suggest', ai_enabled=True,
        personal_active_since=timezone.now() - timedelta(minutes=1),
        execution_snapshot={'model': {'model_id': 'synthetic'}},
    )
    SubscriptionGroupingState.objects.create(subscription=subscription, status='pending')
    with patch('api.services.channel_ai.verify_model', return_value=object()), \
            patch('api.services.channel_model.verify_model', return_value=object()), \
            patch('api.services.channel_grouping.credential_fingerprint', return_value='fingerprint'):
        enqueue_personal_batch(user, [subscription.pk])
    proposal = ChannelGroupingProposal.objects.get(user=user, target='groups', background=True)
    assert proposal.status == 'queued'
    assert proposal.group_snapshot == {'roots': [], 'children': []}
    assert not ChannelGroupRoot.objects.filter(user=user).exists()
    assert not ChannelGroup.objects.filter(user=user).exists()


def test_reliable_rule_auto_assigns_existing_child_but_ai_paths_remain_review_only():
    user = User.objects.create_user('trusted-rule-owner')
    root = ChannelGroupRoot.objects.create(user=user, name='工程')
    child = ChannelGroup.objects.create(user=user, root=root, name='前端')
    source = Source.objects.create(name='Trusted frontend', url='https://example.test/trusted-frontend')
    from api.services.channel_topics import base_profile
    SourceTopicProfile.objects.create(
        source=source, topics=['frontend'], origin='manual', about='Reviewed frontend source',
        evidence_hash=base_profile(source)['evidence_hash'],
    )
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    ChannelGroupingConfig.objects.create(
        user=user, mode='auto', match_existing=True,
        bindings={'frontend': child.pk},
        personal_active_since=timezone.now() - timedelta(minutes=1),
    )
    process_subscription(subscription.pk)
    assert child.subscriptions.filter(pk=subscription.pk).exists()
    proposal = ChannelGroupingProposal.objects.get(user=user, engine='rules', status='applied')
    assert proposal.result[0]['needs_review'] is False
