"""Extract aggregate evidence from an explicitly supplied, standalone SQLite copy."""
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from api.rss.migration_inventory import UNKNOWN
from api.services.source_policy import POLICIES


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def extract_snapshot(path, *, expected_sha256):
    path = Path(path).resolve(strict=True)
    # An online backup is standalone. A main file with an omitted WAL is not.
    wal = Path(str(path) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('use a standalone SQLite online-backup artifact, not an active WAL database')
    with path.open('rb') as stream:
        actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual_hash != expected_sha256:
        raise ValueError('snapshot hash mismatch')
    db = sqlite3.connect('file:' + quote(str(path)) + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('invalid SQLite snapshot')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not {'api_source', 'api_news', 'api_newssourceitem'} <= tables:
            raise ValueError('snapshot lacks legacy source identity schema')
        fingerprints = {}
        for name in sorted(tables):
            # A digest preserves evidence without exporting user content, credentials,
            # tokens, identities or arbitrary fields into a Git-tracked manifest.
            columns = list(db.execute(f'PRAGMA table_info({_identifier(name)})'))
            order = [c['name'] for c in sorted(columns, key=lambda c: c['pk']) if c['pk']]
            if not order:
                order = [c['name'] for c in columns]
            hasher = hashlib.sha256()
            count = 0
            for row in db.execute(f'SELECT * FROM {_identifier(name)} ORDER BY ' + ','.join(map(_identifier, order))):
                payload = json.dumps([{'blob': v.hex()} if isinstance(v, bytes) else v for v in row],
                                     separators=(',', ':'), ensure_ascii=False).encode()
                hasher.update(len(payload).to_bytes(8, 'big'))
                hasher.update(payload)
                count += 1
            fingerprints[name] = {'rows': count, 'sha256': hasher.hexdigest(),
                                  'columns': [c['name'] for c in columns]}
        configs = list(db.execute('SELECT * FROM api_sourceconfig')) if 'api_sourceconfig' in tables else []
        publications = {r['source_id']: dict(r) for r in db.execute('SELECT * FROM api_sourcepublication')} if 'api_sourcepublication' in tables else {}
        sources = []
        for source in db.execute('SELECT * FROM api_source ORDER BY id'):
            sid = source['id']
            # Exact static name mapping is the existing channel_articles contract;
            # never use similarity, article titles or caller-provided display names.
            policies = [p for p in POLICIES.values() if p.name == source['name']]
            dynamic = [c for c in configs if c['source_id'] == sid]
            keys = sorted({p.key for p in policies} | {c['source_key'] for c in dynamic})
            publication = publications.get(sid)
            source_policy = dynamic[0]['reading_policy'] if dynamic else policies[0].reading_policy if policies else UNKNOWN
            sources.append({
                'source_id': sid, 'source_keys': keys, 'display_name': source['name'],
                'identity_evidence': 'legacy_exact_policy_name_and_sourceconfig_fk',
                'publication': publication['publication'] if publication else 'public',
                'reading_policy': publication['reading_policy'] if publication else source_policy,
                'owner': publication['owner'] if publication else 'legacy',
                'epoch': publication['epoch'] if publication else 0,
                'preservation': {'scope': 'snapshot_table_fingerprints', 'snapshot_sha256': actual_hash},
                'legacy_selection': {'dynamic_config_keys': [c['source_key'] for c in dynamic],
                                     'endpoint_evidence': fingerprints.get('api_sourceendpoint', UNKNOWN)},
            })
        # Configurations without a Source FK are not an existing Source ID and must
        # not be fabricated into one; they remain a separate unresolved inventory.
        unbound = [{'source_key': c['source_key'], 'status': c['status'],
                    'reason': 'no_source_fk'} for c in configs if c['source_id'] is None]
        result = {'id': 'sha256:' + actual_hash, 'sources': sources,
                  'table_fingerprints': fingerprints, 'unbound_source_configs': unbound,
                  'evidence_status': 'standalone_copy_read_only', 'production_ready': False}
    finally:
        db.close()
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != actual_hash:
            raise ValueError('snapshot changed during inspection')
    return result
