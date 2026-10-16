"""Read-only source inventory. Unknown deployment facts never become approvals."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from api.services.source_policy import POLICIES

UNKNOWN = 'UNKNOWN'
SPECIAL_RULES = {
    'devto': ('DEV.to top=50 plus six tag APIs, per_page=50; publisher ID deduplication',
              'Generic RSS does not preserve the API popularity/tag selection or detail body contract.'),
    'hackernews': ('Firebase topstories first 80 IDs; live story items only, publisher IDs and discussion URLs',
                  'RSS ranking/count/IDs need comparison; mixed article, repository, video and self-post objects.'),
    'github': ('GitHub Trending daily and weekly HTML; repository metadata and optional README',
               'Requires an approved existing RSSHub route; repository description is not full news.'),
    'arxiv_ai': ('cs.AI+cs.LG+cs.CL Atom categories',
                 'Feed abstracts remain abstracts; no PDF or paper full-text fetching.'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def canonical_feed(url):
    """Inventory grouping only; admission and DNS enforcement remain elsewhere."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('inventory feed must be credential-free HTTPS')
    host = parsed.hostname.lower()
    host = '[' + host + ']' if ':' in host else host
    port = parsed.port
    return urlunsplit(('https', host + (f':{port}' if port and port != 443 else ''),
                       parsed.path, parsed.query, ''))


def static_sources(repo_root):
    """No Django setup, database query, spider import or network request."""
    root = Path(repo_root)
    rows = []
    spider_files = sorted((root / 'crawler/news_crawler/spiders').glob('*.py'))
    for key, policy in sorted(POLICIES.items()):
        files = [p for p in spider_files if f"name = '{key}'" in p.read_text()]
        if not files:
            files = [root / 'backend/api/services/sector_feeds.py'] if policy.default_category else []
        evidence = [{'path': str(p.relative_to(root)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in files]
        rule, difference = SPECIAL_RULES.get(key, (
            f'Configured feed; keyword filter={policy.keyword_filter or "none"}; body fields={list(policy.body_fields)}',
            'Feed candidate is not live-verified; compare article selection and body availability before switching.',
        ))
        restricted = not policy.html_allowed or bool(policy.unsupported_reason)
        rows.append({
            'inventory_key': 'code:' + key, 'source_id': None, 'source_key': key,
            'display_name': policy.name, 'origin': 'code', 'legacy_policy': asdict(policy),
            'legacy_selection': rule, 'code_evidence': evidence,
            'feed_candidates': [policy.feed_url] if policy.feed_url.startswith('https://') else [],
            'target_feed_url': None, 'binding_id': None, 'content_kind': policy.content_kind,
            'desired_mode': 'feed' if restricted or policy.body_fields else 'article',
            'reading_policy': policy.reading_policy, 'publication': UNKNOWN,
            'expected_owner': UNKNOWN, 'expected_epoch': None,
            'coverage_difference': difference, 'decision': 'review_required',
            'unsupported_reason': policy.unsupported_reason, 'preservation': UNKNOWN,
            'body_takeover': [], 'result': 'NOT_RUN',
        })
    return rows


def build_inventory(repo_root, baseline_sha, *, snapshot=None, targets=None):
    """Merge explicit sanitized snapshot evidence, never infer IDs by display name.

    snapshot={id, sources:[{source_id, source_keys, ...}]}; each source is emitted
    once. Extra database sources are retained even without a code policy. Targets
    are reviewer mappings keyed by inventory_key; they confer no switch approval.
    """
    rows = static_sources(repo_root)
    by_key = {row['source_key']: row for row in rows}
    bound_keys = set()
    merged = []
    if snapshot is not None:
        if not isinstance(snapshot, dict) or not snapshot.get('id') or not isinstance(snapshot.get('sources'), list):
            raise ValueError('invalid snapshot evidence')
        seen = set()
        for source in snapshot['sources']:
            sid = source.get('source_id')
            if type(sid) is not int or sid <= 0 or sid in seen:
                raise ValueError('invalid or repeated source ID')
            seen.add(sid)
            keys = source.get('source_keys', [])
            if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
                raise ValueError('invalid source keys')
            related = [by_key[k] for k in keys if k in by_key]
            row = dict(related[0]) if related else {
                'origin': 'database', 'content_kind': source.get('content_kind', UNKNOWN),
                'legacy_selection': source.get('legacy_selection', UNKNOWN),
                'coverage_difference': 'Dynamic endpoint selection requires explicit Feed/route comparison; HTML-only has no automatic fallback.',
                'feed_candidates': [], 'desired_mode': 'feed', 'decision': 'review_required',
                'unsupported_reason': '', 'body_takeover': [], 'result': 'NOT_RUN',
            }
            row.update({
                'inventory_key': f'source:{sid}', 'source_id': sid, 'source_keys': keys,
                'source_key': keys[0] if len(keys) == 1 else None,
                'display_name': source.get('display_name', UNKNOWN),
                'legacy_contracts': related,
                'publication': source.get('publication', UNKNOWN),
                'reading_policy': source.get('reading_policy', UNKNOWN),
                'expected_owner': source.get('owner', UNKNOWN),
                'expected_epoch': source.get('epoch'),
                'preservation': source.get('preservation', UNKNOWN),
                'target_feed_url': None, 'binding_id': None,
            })
            merged.append(row)
            bound_keys.update(keys)
    merged.extend(row for row in rows if row['source_key'] not in bound_keys)
    targets = targets or {}
    if set(targets) - {row['inventory_key'] for row in merged}:
        raise ValueError('mapping names unknown inventory sources')
    groups = {}
    for row in merged:
        target = targets.get(row['inventory_key'])
        if target:
            row['target_feed_url'] = canonical_feed(target)
            groups.setdefault(row['target_feed_url'], []).append(row['inventory_key'])
        row['switch_group'] = None
        row['production_ready'] = False
    switch_groups = []
    for url, members in sorted(groups.items()):
        group_id = 'feed:' + digest(url)[:20]
        switch_groups.append({'id': group_id, 'canonical_feed_url': url, 'members': sorted(members),
                              'completeness': 'requires_snapshot_and_reference_review'})
        for row in merged:
            if row['inventory_key'] in members:
                row['switch_group'] = group_id
    return {'schema_version': 1, 'baseline_sha': baseline_sha,
            'inventory_snapshot_id': snapshot['id'] if snapshot else UNKNOWN,
            'environment': 'inventory_only', 'production_ready': False,
            'snapshot_status': 'provided_unverified' if snapshot else 'BLOCKED',
            'sources': sorted(merged, key=lambda row: row['inventory_key']),
            'unbound_source_configs': snapshot.get('unbound_source_configs', []) if snapshot else [],
            'table_fingerprints': snapshot.get('table_fingerprints', {}) if snapshot else {},
            'switch_groups': switch_groups, 'backup_ref': None, 'compatible_release_ref': None}
