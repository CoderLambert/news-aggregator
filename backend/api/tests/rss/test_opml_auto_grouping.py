"""#15 explicit paths, additive personal organization and stale-preview fences."""
import uuid
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ChannelGroup, ChannelGroupMember, ChannelGroupRoot, ChannelSubscription
from api.rss.directory_models import FeedDirectoryEntry, FeedDirectorySnapshot
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.models import FeedOperation
from api.rss.opml import _group_path_key, process_imports
from api.smart_channel_models import ChannelGroupingOverride
from api.tests.rss.registration_fixtures import connect_pending
from api.tests.rss.test_opml_import import client, confirmation, people  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
URL = 'https://example.com/feed'
PATH = _group_path_key(('技术', 'AI / 大模型'))
XML = f'<opml><body><outline text="技术"><outline text="AI / 大模型"><outline text="One" xmlUrl="{URL}"/></outline></outline></body></opml>'.encode()


def preview(user, raw=XML, *, organize=True):
    data = {'organize_existing': str(organize).lower()}
    if raw is None:
        data['organization_only'] = 'true'
    else:
        data['file'] = SimpleUploadedFile('explicit.opml', raw)
    response = client(user).post('/api/me/rss-imports/preview/', data, format='multipart')
    assert response.status_code == 201, response.data
    return response


def confirm(user, response, **overrides):
    data = confirmation(response, group_map={key: 'auto' for key, plan in response.data['group_plan'].items()
                                           if plan['action'] != 'conflict'}, **overrides)
    return client(user).post('/api/me/rss-imports/confirm/', data, format='json')


def subscribed(user, url=URL):
    result = client(user).post('/api/me/rss-subscriptions/', {'feed_url': url}, format='json',
                              HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
    assert result.status_code in (201, 202), result.data
    connect_pending()
    return ChannelSubscription.objects.get(user=user, source_id=result.data['source_id'])


def catalog(url=URL):
    snapshot = FeedDirectorySnapshot.objects.create(checksum='a' * 64, commit='synthetic', license='test', schema_version=1, active=True)
    FeedDirectoryEntry.objects.create(snapshot=snapshot, entry_id=uuid.uuid4(), name='One', kind='feed', public_url=url,
                                      tags=['newshub:tech:ai-llm'])
    return snapshot


def test_preview_then_confirm_creates_two_levels_once_and_worker_reuses_existing_fences(people):
    a, b = people
    result = preview(a)
    assert result.data['group_plan'][PATH]['action'] == 'create'
    assert result.data['group_plan'][PATH]['name'] == 'AI / 大模型'
    assert not ChannelGroupRoot.objects.exists() and not ChannelSubscription.objects.exists()
    first = confirm(a, result)
    assert first.status_code == 202, first.data
    assert confirm(a, result).status_code == 202
    assert ChannelGroup.objects.filter(user=a, root__name='技术', name='AI / 大模型').count() == 1
    assert not ChannelGroup.objects.filter(user=b).exists()
    assert not ChannelSubscription.objects.exists()
    assert process_imports() == 1
    connect_pending()
    assert ChannelSubscription.objects.get(user=a).groups.get().name == 'AI / 大模型'
    assert confirm(a, result).status_code == 202  # Replay after worker attached its FK.
    repeated = preview(a)
    assert confirm(a, repeated).status_code == 202
    assert process_imports() == 0
    assert ChannelGroup.objects.count() == 1 and ChannelSubscription.objects.count() == 1


def test_parallel_identical_confirmations_create_only_one_structure(people):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    a, _ = people
    result = preview(a)
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return confirm(a, result).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(), range(2)))
    assert statuses == [202, 202]
    assert ChannelGroupRoot.objects.count() == 1 and ChannelGroup.objects.count() == 1
    assert not ChannelSubscription.objects.exists()


def test_exact_path_reuses_owner_group_and_does_not_reuse_foreign_group(people):
    a, b = people
    for user in (a, b):
        root = ChannelGroupRoot.objects.create(user=user, name='技术')
        ChannelGroup.objects.create(user=user, root=root, name='AI / 大模型')
    result = preview(a)
    own = ChannelGroup.objects.get(user=a)
    assert result.data['group_plan'][PATH]['group_id'] == own.pk
    assert confirm(a, result).status_code == 202
    assert RssImportItem.objects.get().selected_group_ids == [own.pk]
    assert ChannelGroup.objects.count() == 2


def test_same_child_in_other_root_is_explained_and_never_moved(people):
    a, _ = people
    root = ChannelGroupRoot.objects.create(user=a, name='我的栏目')
    child = ChannelGroup.objects.create(user=a, root=root, name='AI / 大模型')
    result = preview(a)
    assert result.data['group_plan'][PATH]['action'] == 'conflict'
    assert '父分类不同' in result.data['group_plan'][PATH]['reason']
    response = client(a).post('/api/me/rss-imports/confirm/', confirmation(result, group_map={PATH: 'auto'}), format='json')
    assert response.status_code == 400
    assert ChannelGroupRoot.objects.count() == 1
    assert client(a).post('/api/me/rss-imports/confirm/', confirmation(result, group_map={PATH: child.pk}), format='json').status_code == 202
    child.refresh_from_db()
    assert child.root_id == root.pk


@pytest.mark.parametrize('roots', [('A', 'B'), ('技术', '其他')])
def test_same_named_children_across_import_roots_require_manual_mapping(people, roots):
    a, _ = people
    raw = ('<opml><body>' + ''.join(f'<outline text="{root}"><outline text="Child"><outline xmlUrl="https://example.com/{i}"/></outline></outline>'
                                     for i, root in enumerate(roots)) + '</body></opml>').encode()
    result = preview(a, raw)
    assert all(p['action'] == 'conflict' for p in result.data['group_plan'].values())
    assert confirm(a, result).status_code == 202  # Explicitly no automatic mapping.
    assert not ChannelGroup.objects.exists()


def test_organizes_existing_from_opml_preserves_manual_other_owner_and_unknown(people):
    a, b = people
    existing = subscribed(a)
    manual = subscribed(a, 'https://example.org/manual')
    unknown = subscribed(a, 'https://example.org/unknown')
    other = ChannelSubscription.objects.create(user=b, source=existing.source)
    root = ChannelGroupRoot.objects.create(user=a, name='Personal')
    child = ChannelGroup.objects.create(user=a, root=root, name='Manual')
    manual.groups.add(child)
    result = preview(a)
    candidates = [row for row in result.data['items'] if row['can_organize']]
    assert len(candidates) == 1 and candidates[0]['subscription_id'] == existing.pk
    assert not existing.groups.exists()
    response = confirm(a, result)
    assert response.status_code == 202, response.data
    assert confirm(a, result).status_code == 202
    assert existing.groups.get().name == 'AI / 大模型'
    assert list(manual.groups.all()) == [child]
    assert not other.groups.exists() and not unknown.groups.exists()
    assert not any(item.created_subscription for item in RssImportItem.objects.all())
    assert process_imports() == 0
    assert client(a).delete(f"/api/me/rss-imports/{result.data['id']}/").data['removed_count'] == 0
    assert ChannelSubscription.objects.count() == 4


def test_organize_only_uses_directory_for_owned_subscriptions_not_all_catalog_entries(people):
    a, b = people
    existing = subscribed(a)
    subscribed(b, 'https://other.example/feed')
    snapshot = catalog()
    FeedDirectoryEntry.objects.create(snapshot=snapshot, entry_id=uuid.uuid4(), name='Unsubscribed', kind='feed',
                                      public_url='https://unused.example/feed', tags=['newshub:business:startup-product'])
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        result = preview(a, None)
        response = confirm(a, result)
    assert response.status_code == 202, response.data
    assert len(result.data['items']) == 1 and result.data['organization_only']
    assert existing.groups.get().name == 'AI / 大模型'
    assert ChannelGroupRoot.objects.filter(user=a).get().name == '技术'
    assert ChannelSubscription.objects.count() == 2
    assert not FeedOperation.objects.filter(actor=a, safe_input__bulk_import=True).exists()


def test_organize_only_can_reuse_confirmed_owner_opml_evidence(people):
    a, _ = people
    result = preview(a, organize=False)
    assert confirm(a, result).status_code == 202
    process_imports()
    connect_pending()
    subscription = ChannelSubscription.objects.get(user=a)
    subscription.groups.clear()
    organized = preview(a, None)
    assert organized.data['items'][0]['can_organize']
    assert confirm(a, organized).status_code == 202
    assert subscription.groups.get().name == 'AI / 大模型'


@pytest.mark.parametrize('change', ['membership', 'membership-aba', 'root-version', 'subscription', 'catalog'])
def test_concurrent_changes_reject_entire_preview_without_new_groups(people, change):
    a, _ = people
    subscription = subscribed(a)
    root = ChannelGroupRoot.objects.create(user=a, name='Personal')
    child = ChannelGroup.objects.create(user=a, root=root, name='Manual')
    result = preview(a)
    if change.startswith('membership'):
        assert client(a).post('/api/me/channel-subscriptions/', {'action': 'add_to_group',
            'source_ids': [subscription.source_id], 'group_id': child.pk}, format='json').status_code == 200
        if change == 'membership-aba':
            assert client(a).patch(f'/api/me/channel-groups/{child.pk}/', {'remove_source_ids': [subscription.source_id]}, format='json').status_code == 200
    elif change == 'root-version':
        root.version += 1
        root.save()
    elif change == 'subscription':
        subscription.delete()
    else:
        catalog()
    response = confirm(a, result)
    assert response.status_code == 409, response.data
    assert not ChannelGroupRoot.objects.filter(user=a, name='技术').exists()
    assert RssImportBatch.objects.get(pk=result.data['id']).status == 'preview'


def test_manual_grouping_between_confirm_and_worker_completion_is_preserved(people):
    a, _ = people
    result = preview(a)
    assert confirm(a, result).status_code == 202
    assert process_imports() == 1
    item = RssImportItem.objects.select_related('operation').get()
    source_id = item.operation.safe_input['subscription_request']['source_id']
    subscription = ChannelSubscription.objects.create(user=a, source_id=source_id)
    root = ChannelGroupRoot.objects.create(user=a, name='Personal')
    manual = ChannelGroup.objects.create(user=a, root=root, name='Manual')
    subscription.groups.add(manual)
    connect_pending()
    assert list(subscription.groups.all()) == [manual]


def test_owner_csrf_expiry_and_changed_replay_fail_closed(people):
    a, b = people
    result = preview(a)
    data = confirmation(result, group_map={PATH: 'auto'})
    assert client(b).post('/api/me/rss-imports/confirm/', data, format='json').status_code == 404
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(a)
    assert session.post('/api/me/rss-imports/preview/', {'organize_existing': True, 'organization_only': True}, format='json').status_code == 403
    assert session.post('/api/me/rss-imports/confirm/', data, format='json').status_code == 403
    assert APIClient().post('/api/me/rss-imports/preview/', {}, format='json').status_code == 401
    RssImportBatch.objects.filter(pk=result.data['id']).update(expires_at=timezone.now())
    assert confirm(a, result).status_code == 400
    assert not ChannelGroup.objects.exists()


def test_changed_confirmation_is_rejected_but_identical_retry_survives_structure_changes(people):
    a, _ = people
    result = preview(a)
    assert confirm(a, result).status_code == 202
    ChannelGroupRoot.objects.create(user=a, name='Later manual root')
    assert confirm(a, result).status_code == 202
    changed = confirmation(result, group_map={PATH: None})
    assert client(a).post('/api/me/rss-imports/confirm/', changed, format='json').status_code == 409


@pytest.mark.parametrize('limit', ['root', 'child'])
def test_auto_group_limits_and_transaction_failure_leave_no_partial_writes(people, limit):
    a, _ = people
    if limit == 'root':
        ChannelGroupRoot.objects.bulk_create([ChannelGroupRoot(user=a, name=f'root{i}') for i in range(40)])
    else:
        root = ChannelGroupRoot.objects.create(user=a, name='Personal')
        ChannelGroup.objects.bulk_create([ChannelGroup(user=a, root=root, name=f'child{i}') for i in range(200)])
    result = preview(a)
    assert confirm(a, result).status_code == 400
    assert not ChannelGroupRoot.objects.filter(name='技术').exists()
    assert RssImportBatch.objects.get(pk=result.data['id']).status == 'preview'


def test_failure_during_assignment_rolls_back_created_structure(people):
    a, _ = people
    subscription = subscribed(a)
    result = preview(a)
    with patch('api.rss.opml_grouping.ChannelGroupMember.objects.bulk_create', side_effect=IntegrityError('synthetic')):
        with pytest.raises(IntegrityError):
            confirm(a, result)
    assert not ChannelGroupRoot.objects.exists()
    assert not subscription.groups.exists()
    assert RssImportBatch.objects.get(pk=result.data['id']).confirmed_request_hash == ''


def test_suppressed_manual_assignment_is_not_restored(people):
    a, _ = people
    subscription = subscribed(a)
    root = ChannelGroupRoot.objects.create(user=a, name='技术')
    child = ChannelGroup.objects.create(user=a, root=root, name='AI / 大模型')
    ChannelGroupingOverride.objects.create(user=a, source=subscription.source, group=child, suppressed=True)
    result = preview(a)
    assert confirm(a, result).status_code == 409
    assert not subscription.groups.exists()


def test_more_than_three_groups_rejected_atomically(people):
    a, _ = people
    raw = ('<opml><body>' + ''.join(f'<outline text="Root"><outline text="Child{i}"><outline xmlUrl="{URL}"/></outline></outline>'
                                     for i in range(4)) + '</body></opml>').encode()
    result = preview(a, raw)
    assert confirm(a, result).status_code == 400
    assert not ChannelGroup.objects.exists()


def test_personal_500_limit_does_not_silently_admit_502_public_catalog(people):
    a, _ = people
    def raw(count):
        return ('<opml><body>' + ''.join(f'<outline xmlUrl="https://example.com/feed/{i}"/>' for i in range(count)) + '</body></opml>').encode()
    assert preview(a, raw(500)).data['total'] == 500
    response = client(a).post('/api/me/rss-imports/preview/', {'file': SimpleUploadedFile('catalog.opml', raw(502))}, format='multipart')
    assert response.status_code == 400 and '502项公共目录' in str(response.data)
    assert RssImportBatch.objects.count() == 1 and not ChannelSubscription.objects.exists()
