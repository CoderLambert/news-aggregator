"""Default catalog integration; isolated Django DB, no Miniflux or publishers."""
import hashlib
from io import StringIO
from xml.etree import ElementTree as ET
from unittest.mock import patch

import pytest
from django.core import signing
from django.core.management import call_command
from django.core.management.base import CommandError

from api.rss.catalog_taxonomy import SECTIONS
from api.rss.catalog_import import plan_catalog_import, apply_catalog_plan, rollback_catalog
from api.rss.directory import import_pinned_seed, search_directory, DirectoryCursorError
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
