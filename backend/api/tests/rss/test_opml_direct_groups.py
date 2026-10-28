"""#15 local-UAT correction: one OPML level is a real parentless personal group."""
from xml.etree import ElementTree as ET

import pytest
from rest_framework.test import APIClient

from api.channel_views import scoped_sources
from api.models import ChannelGroup, ChannelGroupRoot, ChannelSubscription, NewsPreference
from api.rss.import_models import RssImportBatch
from api.rss.opml import _group_path_key, process_imports
from api.services.channel_grouping import hierarchy_state, private_groups, undo_proposal
from api.smart_channel_models import ChannelGroupingProposal
from django.utils import timezone
from api.tests.rss.registration_fixtures import connect_pending
from api.tests.rss.test_opml_auto_grouping import confirm, preview, subscribed
from api.tests.rss.test_opml_import import client, confirmation, people  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
NAME = '🌐 科技媒体与开源生态深度阅读'
URL = 'https://example.com/direct-feed'
FLAT = f'<opml><body><outline text="{NAME}"><outline text="Feed" xmlUrl="{URL}"/></outline></body></opml>'.encode()


def test_single_level_creates_and_reuses_direct_group_and_exports_one_level(people):
    a, _ = people
    result = preview(a, FLAT)
    plan = result.data['group_plan'][NAME]
    assert plan['root_name'] is None and not plan['create_root']
    assert not ChannelGroup.objects.exists() and not ChannelGroupRoot.objects.exists()
    assert confirm(a, result).status_code == 202
    group = ChannelGroup.objects.get(user=a)
    assert group.name == NAME and group.root_id is None
    assert not ChannelGroupRoot.objects.exists()
    assert confirm(a, result).status_code == 202
    process_imports()
    connect_pending()
    subscription = ChannelSubscription.objects.get(user=a)
    assert subscription.groups.get().pk == group.pk
    exported = client(a).get('/api/me/rss-subscriptions/export/')
    body = ET.fromstring(exported.content).find('body')
    assert len(body) == 1 and body[0].attrib['text'] == NAME
    assert body[0][0].attrib['xmlUrl'] == URL and body[0][0].attrib['type'] == 'rss'
    repeated = preview(a, exported.content)
    assert repeated.data['group_matches'] == {NAME: group.pk}
    assert repeated.data['group_plan'][NAME]['action'] == 'reuse'
    assert confirm(a, repeated).status_code == 202
    assert ChannelGroup.objects.count() == 1 and not ChannelGroupRoot.objects.exists()
    assert list(scoped_sources(a, 'group', group)) == [subscription.source_id]
    assert private_groups(a)['children'][0]['path'] == NAME
    assert hierarchy_state(a)['children'][0]['root_id'] is None


def test_existing_ungrouped_organization_uses_direct_group_without_moving_manual_or_unknown(people):
    a, b = people
    known = subscribed(a, URL)
    manual = subscribed(a, 'https://example.com/manual')
    unknown = subscribed(a, 'https://example.com/unknown')
    other = ChannelSubscription.objects.create(user=b, source=known.source)
    root = ChannelGroupRoot.objects.create(user=a, name='手工栏目')
    group = ChannelGroup.objects.create(user=a, root=root, name='手工分组')
    manual.groups.add(group)
    result = preview(a, FLAT)
    assert confirm(a, result).status_code == 202
    assert known.groups.get().name == NAME and known.groups.get().root_id is None
    assert list(manual.groups.all()) == [group]
    assert not unknown.groups.exists() and not other.groups.exists()
    assert list(ChannelGroupRoot.objects.values_list('name', flat=True)) == ['手工栏目']
    assert process_imports() == 0


def test_real_two_level_path_including_opml_named_parent_is_not_flattened(people):
    a, _ = people
    raw = '<opml><body><outline text="OPML 导入"><outline text="技术媒体"><outline xmlUrl="https://example.com/nested"/></outline></outline></body></opml>'.encode()
    result = preview(a, raw)
    path = _group_path_key(('OPML 导入', '技术媒体'))
    assert result.data['group_plan'][path]['root_name'] == 'OPML 导入'
    assert confirm(a, result).status_code == 202
    group = ChannelGroup.objects.get(user=a)
    assert group.root.name == 'OPML 导入' and group.name == '技术媒体'


def test_nested_existing_group_is_never_implicitly_promoted_by_name_or_import(people):
    a, b = people
    subscription = subscribed(a, URL)
    root = ChannelGroupRoot.objects.create(user=a, name='OPML 导入')
    group = ChannelGroup.objects.create(user=a, root=root, name=NAME)
    group.subscriptions.add(subscription)
    other_root = ChannelGroupRoot.objects.create(user=b, name='OPML 导入')
    other_group = ChannelGroup.objects.create(user=b, root=other_root, name=NAME)
    preference = NewsPreference.objects.create(user=a, scope='group', group=group)
    result = preview(a, FLAT)
    assert result.data['group_plan'][NAME]['action'] == 'conflict'
    assert confirm(a, result).status_code == 202  # Existing manually grouped row is skipped.
    group.refresh_from_db()
    assert group.root_id == root.pk
    # Only an explicit, versioned owner mutation changes the structure, not the group identity.
    payload = {'root_id': None, 'expected_version': group.version}
    path = f'/api/me/channel-groups/{group.pk}/'
    assert client(b).patch(path, payload, format='json').status_code == 404
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(a)
    assert session.patch(path, payload, format='json').status_code == 403
    assert client(a).patch(path, {**payload, 'expected_version': group.version + 1}, format='json').status_code == 409
    changed = client(a).patch(path, payload, format='json')
    assert changed.status_code == 200 and changed.data['root_id'] is None
    group.refresh_from_db(); preference.refresh_from_db(); other_group.refresh_from_db()
    assert group.root_id is None and group.name == NAME
    assert list(group.subscriptions.all()) == [subscription]
    assert preference.group_id == group.pk
    assert ChannelGroupRoot.objects.filter(pk=root.pk).exists()
    assert other_group.root_id == other_root.pk
    assert client(a).patch(path, payload, format='json').status_code == 409


def test_direct_creation_reparenting_and_orphan_validation_preserve_owner_contract(people):
    a, b = people
    created = client(a).post('/api/me/channel-groups/', {'name': NAME, 'root_id': None}, format='json')
    assert created.status_code == 201 and created.data['root_id'] is None
    group = ChannelGroup.objects.get(user=a)
    foreign = ChannelGroupRoot.objects.create(user=b, name='Private')
    path = f'/api/me/channel-groups/{group.pk}/'
    for bad in (foreign.pk, 999999, True, 'direct'):
        assert client(a).patch(path, {'root_id': bad, 'expected_version': group.version}, format='json').status_code in (400, 404)
    assert group.root_id is None
    own = ChannelGroupRoot.objects.create(user=a, name='真实父分类')
    response = client(a).patch(path, {'root_id': own.pk, 'expected_version': group.version}, format='json')
    assert response.status_code == 200 and response.data['root_id'] == own.pk


def test_direct_group_does_not_require_an_additional_root_slot(people):
    a, _ = people
    ChannelGroupRoot.objects.bulk_create([ChannelGroupRoot(user=a, name=f'栏目{i}') for i in range(40)])
    result = preview(a, FLAT)
    assert confirm(a, result).status_code == 202
    assert ChannelGroup.objects.get(user=a).root_id is None
    assert ChannelGroupRoot.objects.count() == 40


@pytest.mark.parametrize('newer_edit', [False, True])
def test_hierarchy_undo_can_restore_a_direct_parent_without_overwriting_newer_edits(people, newer_edit):
    a, _ = people
    root = ChannelGroupRoot.objects.create(user=a, name='真实父分类')
    group = ChannelGroup.objects.create(user=a, root=root, name=NAME, version=3 if newer_edit else 2)
    proposal = ChannelGroupingProposal.objects.create(user=a, target='hierarchy', status='applied',
        input_snapshot='', expires_at=timezone.now(), applied_changes=[{
            'child_id': group.pk, 'before_root_id': None, 'before_version': 1,
            'after_root_id': root.pk, 'after_version': 2,
        }])
    undo_proposal(a, proposal.pk)
    group.refresh_from_db()
    assert group.root_id == (root.pk if newer_edit else None)
    assert ChannelGroupRoot.objects.filter(pk=root.pk).exists()


def test_unconfirmed_old_auto_group_plan_requires_new_preview(people):
    a, _ = people
    result = preview(a, FLAT)
    batch = RssImportBatch.objects.get(pk=result.data['id'])
    batch.options.pop('grouping_schema')
    batch.options['group_plan'][NAME]['root_name'] = 'OPML 导入'
    batch.save(update_fields=['options'])
    response = client(a).post('/api/me/rss-imports/confirm/', confirmation(result, group_map={NAME: 'auto'}), format='json')
    assert response.status_code == 409
    assert not ChannelGroup.objects.exists() and not ChannelGroupRoot.objects.exists()
