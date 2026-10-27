"""Default catalog integration; isolated Django DB, no Miniflux or publishers."""
import hashlib
import json
from io import StringIO
from xml.etree import ElementTree as ET
from unittest.mock import patch

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.management import call_command
from django.core.management.base import CommandError

from api.rss.catalog_taxonomy import SECTIONS
from api.rss.catalog_import import plan_catalog_import, apply_catalog_plan, rollback_catalog
from api.rss.directory import import_pinned_seed, import_snapshot, search_directory, DirectoryCursorError, SEED_PATH
from api.rss.directory_models import FeedDirectoryEntry, FeedDirectorySnapshot
from api.models import ChannelSubscription, ChannelGroup, ChannelGroupRoot
from api.rss.models import FeedBinding, FeedOperation

pytestmark = pytest.mark.django_db(transaction=True)


def bundle():
    root = ET.Element('opml', version='2.0')
    body = ET.SubElement(root, 'body')
    for section in SECTIONS:
        parent = ET.SubElement(body, 'outline', text=section['label'])
        for group in section['groups']:
            child = ET.SubElement(parent, 'outline', text=group['label'])
            for i in range(20):
                ET.SubElement(child, 'outline', text=f"{group['key']} {i:02d}", language='en',
                              xmlUrl=f"https://publisher.example/{group['key']}/{i}.xml")
    return ET.tostring(root, encoding='utf-8')


def test_dry_run_preserves_seed_and_does_not_write_or_fetch():
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        plan = plan_catalog_import(bundle())
    assert plan.previous_checksum is None
    assert plan.report['seed_included'] is True
    assert plan.report['incoming'] == 420
    assert plan.report['total_entries'] > 420
    assert not FeedDirectorySnapshot.objects.exists()
    assert not FeedDirectoryEntry.objects.exists()
    assert len(plan.report['sections']) == 5


def test_apply_is_idempotent_and_never_creates_personal_or_engine_state():
    plan = plan_catalog_import(bundle())
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        result = apply_catalog_plan(plan, expected_active=None)
        repeat = plan_catalog_import(bundle())
        repeated = apply_catalog_plan(repeat, expected_active=result['active_checksum'])
    assert repeated['changed'] is False
    assert FeedDirectorySnapshot.objects.count() == 1
    assert not ChannelSubscription.objects.exists()
    assert not ChannelGroup.objects.exists()
    assert not ChannelGroupRoot.objects.exists()
    assert not FeedBinding.objects.exists()
    assert not FeedOperation.objects.exists()
    assert not FeedDirectoryEntry.objects.exclude(verified_at=None).exists()


def test_existing_identity_and_old_directory_survive_apply_and_rollback():
    original = import_pinned_seed()
    identities = set(original.entries.values_list('entry_id', flat=True))
    plan = plan_catalog_import(bundle())
    result = apply_catalog_plan(plan, expected_active=original.checksum)
    active = FeedDirectorySnapshot.objects.get(active=True)
    assert identities <= set(active.entries.values_list('entry_id', flat=True))
    rollback_catalog(original.checksum, expected_active=result['active_checksum'])
    assert FeedDirectorySnapshot.objects.get(active=True).pk == original.pk
    assert FeedDirectorySnapshot.objects.count() == 2


def test_stale_plan_and_wrong_checksum_never_replace_current_snapshot():
    original = import_pinned_seed()
    plan = plan_catalog_import(bundle())
    with pytest.raises(ValueError, match='changed'):
        apply_catalog_plan(plan, expected_active='0' * 64)
    assert FeedDirectorySnapshot.objects.get(active=True).pk == original.pk
    apply_catalog_plan(plan, expected_active=original.checksum)
    with pytest.raises(ValueError, match='changed'):
        apply_catalog_plan(plan, expected_active=original.checksum)


def test_failed_snapshot_write_rolls_back_activation():
    original = import_pinned_seed()
    plan = plan_catalog_import(bundle())
    with patch('api.rss.directory.FeedDirectoryEntry.objects.bulk_create', side_effect=RuntimeError('synthetic')):
        with pytest.raises(RuntimeError):
            apply_catalog_plan(plan, expected_active=original.checksum)
    assert FeedDirectorySnapshot.objects.get(active=True).pk == original.pk
    assert FeedDirectorySnapshot.objects.count() == 1


def test_catalog_filters_counts_cursor_and_legacy_categories_are_compatible():
    plan = plan_catalog_import(bundle())
    apply_catalog_plan(plan, expected_active=None)
    page = search_directory(group='frontend', section='tech', language='en', limit=3)
    assert page['total'] == 20
    assert len(page['results']) == 3
    assert all(r['catalog_paths'][0]['group_key'] == 'frontend' for r in page['results'])
    tech = next(s for s in page['sections'] if s['key'] == 'tech')
    assert next(g for g in tech['groups'] if g['key'] == 'frontend')['count'] == 20
    assert search_directory(group='frontend', section='tech', language='en', limit=3,
                            cursor=page['next_cursor'])['results'] != page['results']
    for changed in ({'group': 'ai-llm'}, {'section': ''}, {'language': ''}, {'region': 'international'}):
        args = {'group': 'frontend', 'section': 'tech', 'language': 'en', 'limit': 3}
        args.update(changed)
        with pytest.raises(DirectoryCursorError):
            search_directory(cursor=page['next_cursor'], **args)
    assert search_directory(category='engineering')['results']
    version = FeedDirectorySnapshot.objects.get(active=True).checksum
    legacy_cursor = signing.dumps({'snapshot': version, 'query': '', 'category': '',
                                   'order_version': 2, 'offset': 1}, salt='rss-directory-v1')
    assert search_directory(cursor=legacy_cursor)['results']
    with pytest.raises(DirectoryCursorError):
        search_directory(cursor=legacy_cursor, section='tech')


def test_command_requires_explicit_apply_hash_version_and_provenance(tmp_path):
    path = tmp_path / 'catalog.opml'
    raw = bundle(); path.write_bytes(raw)
    with pytest.raises(CommandError):
        call_command('import_curated_rss_catalog', file=str(path), apply=True)
    assert not FeedDirectorySnapshot.objects.exists()
    out = StringIO()
    call_command('import_curated_rss_catalog', file=str(path), dry_run=True, stdout=out)
    assert '"incoming": 420' in out.getvalue()
    with pytest.raises(CommandError, match='checksum'):
        call_command('import_curated_rss_catalog', file=str(path), apply=True,
                     input_sha256='0'*64, plan_sha256='0'*64, expected_active='none', acknowledge_provenance=True)
    call_command('import_curated_rss_catalog', file=str(path), apply=True,
                 input_sha256=hashlib.sha256(raw).hexdigest(), plan_sha256=plan_catalog_import(raw).checksum, expected_active='none',
                 acknowledge_provenance=True, stdout=StringIO())
    assert FeedDirectorySnapshot.objects.filter(active=True).count() == 1


def test_runtime_seed_refresh_cannot_undo_import_or_rollback():
    original = import_pinned_seed()
    plan = plan_catalog_import(bundle())
    result = apply_catalog_plan(plan, expected_active=original.checksum)
    assert import_pinned_seed().checksum == result['active_checksum']
    assert FeedDirectorySnapshot.objects.get(active=True).checksum == result['active_checksum']
    rollback_catalog(original.checksum, expected_active=result['active_checksum'])
    with patch('pathlib.Path.read_bytes', side_effect=AssertionError('manual catalog must stay pinned')):
        assert import_pinned_seed().checksum == original.checksum
    assert FeedDirectorySnapshot.objects.get(active=True).provenance['activation_policy'] == 'manual'


def directory_state():
    return {
        model._meta.label: list(model.objects.order_by(model._meta.pk.name).values())
        for model in (FeedDirectorySnapshot, FeedDirectoryEntry)
    }


def non_directory_state():
    # Compare full rows/relations, not just counts; include nonempty personal state.
    return {
        model._meta.label: list(model.objects.order_by(model._meta.pk.name).values())
        for model in apps.get_models(include_auto_created=True)
        if model not in (FeedDirectorySnapshot, FeedDirectoryEntry)
    }


@pytest.mark.parametrize('invalid', ['input_sha256', 'plan_sha256', 'expected_active', 'acknowledge_provenance'])
def test_command_rejects_each_apply_guard_without_any_writes(tmp_path, invalid):
    original = import_pinned_seed()
    raw = bundle()
    path = tmp_path / 'catalog.opml'
    path.write_bytes(raw)
    plan = plan_catalog_import(raw)
    options = dict(file=str(path), apply=True, input_sha256=plan.input_checksum,
                   plan_sha256=plan.checksum, expected_active=original.checksum,
                   acknowledge_provenance=True, stdout=StringIO())
    options[invalid] = False if invalid == 'acknowledge_provenance' else '0' * 64
    before = directory_state(), non_directory_state()
    with pytest.raises(CommandError):
        call_command('import_curated_rss_catalog', **options)
    assert (directory_state(), non_directory_state()) == before


def test_apply_rollback_reapply_preserves_nonempty_personal_state_and_reuses_snapshots():
    user = get_user_model().objects.create_user('catalog-sentinel')
    root = ChannelGroupRoot.objects.create(user=user, name='Private root')
    ChannelGroup.objects.create(user=user, root=root, name='Private group')
    original = import_pinned_seed()
    before = non_directory_state()
    plan = plan_catalog_import(bundle())
    result = apply_catalog_plan(plan, expected_active=original.checksum)
    published_rows = directory_state()['api.FeedDirectoryEntry']
    with pytest.raises(ValueError, match='not found'):
        rollback_catalog('0' * 64, expected_active=result['active_checksum'])
    assert FeedDirectorySnapshot.objects.get(active=True).checksum == result['active_checksum']
    with pytest.raises(ValueError, match='changed'):
        rollback_catalog(original.checksum, expected_active=original.checksum)
    rollback_catalog(original.checksum, expected_active=result['active_checksum'])
    new_plan = plan_catalog_import(bundle())
    reapplied = apply_catalog_plan(new_plan, expected_active=original.checksum)
    assert reapplied['active_checksum'] == result['active_checksum']
    assert FeedDirectorySnapshot.objects.count() == 2
    assert FeedDirectorySnapshot.objects.filter(active=True).count() == 1
    assert directory_state()['api.FeedDirectoryEntry'] == published_rows
    assert non_directory_state() == before


def test_existing_metadata_identity_and_hidden_minimum_are_protected():
    document = json.loads(SEED_PATH.read_bytes())
    row = document['entries'][0]
    row['public_url'] = 'https://publisher.example/frontend/0.xml'
    payload = json.dumps(document).encode()
    original = import_snapshot(payload, expected_checksum=hashlib.sha256(payload).hexdigest())
    old = original.entries.get(public_url=row['public_url'])
    before = {field: getattr(old, field) for field in (
        'entry_id', 'name', 'description', 'language', 'region', 'origin', 'kind',
        'visibility', 'verified_at', 'required_parameters', 'capability_requirements')}
    plan = plan_catalog_import(bundle())
    assert plan.report['reused'] == 1
    assert plan.report['incoming'] == plan.report['added'] + plan.report['reused'] + plan.report['suppressed']
    apply_catalog_plan(plan, expected_active=original.checksum)
    current = FeedDirectorySnapshot.objects.get(active=True).entries.get(entry_id=old.entry_id)
    assert {field: getattr(current, field) for field in before} == before
    assert set(current.tags) == set(old.tags) | {
        'newshub:tech:frontend', '技术', '前端开发', 'Engineering & Technology',
    }
    # An operator-hidden incoming URL leaves only 19 public entries in its group.
    # Refuse the whole plan instead of restoring it or lowering the minimum.
    row['visibility'] = 'hidden'
    payload = json.dumps(document).encode()
    import_snapshot(payload, expected_checksum=hashlib.sha256(payload).hexdigest())
    before = directory_state()
    with pytest.raises(ValueError, match='minimum'):
        plan_catalog_import(bundle())
    assert directory_state() == before


def test_seed_refresh_rechecks_manual_policy_after_reading_seed_bytes():
    original = import_pinned_seed()
    plan = plan_catalog_import(bundle())
    read_bytes = type(SEED_PATH).read_bytes
    published = []

    def publish_during_seed_read(path):
        payload = read_bytes(path)
        if path == SEED_PATH and not published:
            published.append(apply_catalog_plan(plan, expected_active=original.checksum))
        return payload

    with patch('pathlib.Path.read_bytes', new=publish_during_seed_read):
        refreshed = import_pinned_seed()
    assert len(published) == 1
    assert refreshed.checksum == published[0]['active_checksum']
    assert FeedDirectorySnapshot.objects.get(active=True).pk == refreshed.pk
    assert refreshed.provenance['activation_policy'] == 'manual'


def test_catalog_http_filters_pagination_and_errors_do_not_write(settings):
    from rest_framework.test import APIClient
    settings.PUBLIC_SITE_MODE = 'full'
    plan = plan_catalog_import(bundle())
    apply_catalog_plan(plan, expected_active=None)
    before = directory_state(), non_directory_state()
    api = APIClient()
    filters = dict(section='tech', group='frontend', language='en', limit=3)
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        response = api.get('/api/rss/directory/', filters)
        assert response.status_code == 200, response.data
        assert response.data['total'] == 20
        assert len(response.data['categories']) == 9
        assert len(response.data['sections']) == 5
        assert sum(len(section['groups']) for section in response.data['sections']) == 21
        assert response.data['count_scope'] == 'public_catalog_unique_feed_urls'
        ids = []
        sections = response.data['sections']
        while True:
            assert response.status_code == 200
            assert response.data['total'] == 20
            assert response.data['sections'] == sections
            assert all(row['catalog_paths'][0]['group_key'] == 'frontend' for row in response.data['results'])
            ids.extend(row['id'] for row in response.data['results'])
            cursor = response.data['next_cursor']
            if cursor is None:
                break
            response = api.get('/api/rss/directory/', {**filters, 'cursor': cursor})
        assert len(ids) == len(set(ids)) == 20
        for extra in ({'q': 'no-match'}, {'region': 'international'}):
            empty = api.get('/api/rss/directory/', {**filters, **extra})
            assert empty.status_code == 200 and empty.data['results'] == []
            assert empty.data['total'] == 0 and empty.data['sections'] == sections
        for invalid in ({'section': 'unknown'}, {'section': 'business', 'group': 'frontend'},
                        {'group': 'missing'}, {'limit': 0}, {'cursor': 'forged'}, {'q': 'x' * 201}):
            assert api.get('/api/rss/directory/', invalid).status_code == 400
    assert (directory_state(), non_directory_state()) == before
