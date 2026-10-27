"""Operator-only default catalog planning/publication. No subscription writes.

The local OPML content digest pins the authored input, not an invented Git commit
or publisher health result. Existing collection attributions remain unchanged.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from django.db import transaction

from .catalog_opml import ENTRY_FIELDS, check_minimum, encode_snapshot, merge_catalog, parse_catalog_opml
from .directory import (
    MAX_BYTES, SEED_PATH, DirectoryValidationError, _public_url, _source,
    import_snapshot, validate_snapshot,
)
from .directory_models import FeedDirectorySnapshot

SOURCE_ID = 'newshub-curated-opml-v1'
SOURCE_URL = 'https://github.com/CoderLambert/news-aggregator'


@dataclass(frozen=True)
class CatalogPlan:
    payload: bytes
    previous_checksum: str | None
    input_checksum: str
    checksum: str
    report: dict


def _seed_entries():
    """Read the pinned seed without activating it or invoking any worker."""
    with SEED_PATH.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    lock = json.loads(SEED_PATH.with_suffix('.lock.json').read_text(encoding='utf-8'))
    return validate_snapshot(raw, expected_checksum=lock['sha256'])[2]


def plan_catalog_import(raw, *, source_license='NOASSERTION'):
    digest = hashlib.sha256(raw).hexdigest()
    source = _source({'id': SOURCE_ID, 'commit': digest, 'license': source_license, 'url': SOURCE_URL})
    incoming = parse_catalog_opml(raw, validate_url=_public_url, minimum=20)
    snapshot = FeedDirectorySnapshot.objects.filter(active=True).first()
    existing = (list(snapshot.entries.values(*ENTRY_FIELDS, 'origin', 'verified_at'))
                if snapshot else _seed_entries())
    document, report = merge_catalog(existing, incoming, source)
    payload = encode_snapshot(document)
    checksum = hashlib.sha256(payload).hexdigest()
    # Use the SAME validator as publication, including byte/collection/ID limits.
    normalized = validate_snapshot(payload, expected_checksum=checksum)[2]
    report['sections'] = check_minimum(normalized, 20)
    previous = snapshot.checksum if snapshot else None
    report.update(input_checksum=digest, previous_checksum=previous,
                  proposed_checksum=checksum, seed_included=snapshot is None,
                  source=source, source_revision_kind='opml_sha256',
                  changed=checksum != previous, health='not_verified_by_newshub',
                  count_scope='public_catalog_unique_feed_urls')
    return CatalogPlan(payload, previous, digest, checksum, report)


def _checksum(value, *, allow_none=False):
    if allow_none and value is None:
        return value
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise DirectoryValidationError('invalid snapshot checksum')
    return value


def _reserve_and_compare(expected):
    # Project DB is SQLite WAL. This first write reserves the writer before the
    # comparison; select_for_update alone would NOT lock SQLite rows. No network.
    FeedDirectorySnapshot.objects.filter(active=True).update(active=True)
    current = FeedDirectorySnapshot.objects.filter(active=True).first()
    checksum = current.checksum if current else None
    if checksum != expected:
        raise DirectoryValidationError('active catalog changed; run dry-run again')
    return current


def apply_catalog_plan(plan, *, expected_active):
    _checksum(expected_active, allow_none=True)
    if expected_active != plan.previous_checksum:
        raise DirectoryValidationError('active catalog changed; run dry-run again')
    with transaction.atomic():
        current = _reserve_and_compare(expected_active)
        if current and current.checksum == plan.checksum:
            current.provenance = {**current.provenance, 'activation_policy': 'manual'}
            current.save(update_fields=['provenance'])
            return {**plan.report, 'applied': True, 'changed': False,
                    'active_checksum': current.checksum}
        snapshot = import_snapshot(plan.payload, expected_checksum=plan.checksum)
        snapshot.provenance = {**snapshot.provenance, 'activation_policy': 'manual'}
        snapshot.save(update_fields=['provenance'])
    return {**plan.report, 'applied': True, 'active_checksum': snapshot.checksum}


def rollback_catalog(target_checksum, *, expected_active):
    """Activate a retained snapshot; do not delete rows or undo subscriptions."""
    _checksum(target_checksum)
    _checksum(expected_active)
    with transaction.atomic():
        current = _reserve_and_compare(expected_active)
        target = FeedDirectorySnapshot.objects.filter(checksum=target_checksum).first()
        if target is None:
            raise DirectoryValidationError('rollback snapshot not found')
        if current.pk != target.pk:
            FeedDirectorySnapshot.objects.filter(active=True).update(active=False)
            target.active = True
            target.save(update_fields=['active'])
        target.provenance = {**target.provenance, 'activation_policy': 'manual'}
        target.save(update_fields=['provenance'])
    return {'applied': True, 'previous_checksum': expected_active,
            'active_checksum': target.checksum, 'changed': expected_active != target.checksum}
