"""Offline public-catalog OPML parsing and lossless snapshot merge planning.

Not a feed fetcher or a personal OPML importer. URL policy is supplied by the
existing directory service; this module never resolves hosts or performs I/O.
"""
import copy
import hashlib
import json
from collections import defaultdict
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .catalog_taxonomy import PATHS, catalog_tag, taxonomy_counts, url_key

MAX_BYTES = 8 * 1024 * 1024
MAX_FEEDS = 10000
MAX_NODES = 30000
LEGACY_TAGS = {
    'ai-llm': 'Artificial Intelligence', 'frontend': 'Engineering & Technology',
    'backend-architecture': 'Engineering & Technology', 'open-source-ecosystem': 'Engineering & Technology',
    'devops-cloud': 'Engineering & Technology', 'network-security': 'Security',
    'devtools': 'Engineering & Technology', 'bigtech-engineering': 'Engineering & Technology',
    'open-source-trends': 'Communities', 'technology-business': 'Technology Media',
    'startup-product': 'Business & Startups', 'investment-market': 'Business & Startups',
    'healthcare': 'Research & Science', 'energy': 'Research & Science', 'automotive': 'Technology Media',
    'consumer-electronics': 'Technology Media', 'semiconductors': 'Engineering & Technology',
    'world-news': 'News', 'china-news': 'News', 'policy-regulation': 'News',
    'longreads-stories': 'Culture & Ideas',
}
ENTRY_FIELDS = ('name', 'description', 'language', 'region', 'tags', 'kind', 'public_url',
                'required_parameters', 'capability_requirements', 'visibility')


def text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError('invalid catalog label')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('control characters in catalog label')
    return value.strip()


def check_minimum(rows, minimum):
    if type(minimum) is not int or minimum < 0:
        raise ValueError('invalid group minimum')
    tree = taxonomy_counts(rows)
    gaps = [f"{s['key']}/{g['key']}:{g['count']}" for s in tree for g in s['groups']
            if g['count'] < minimum]
    if gaps:
        raise ValueError('catalog group minimum not met: ' + ', '.join(gaps))
    return tree


def parse_catalog_opml(raw, *, validate_url, minimum=20):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('catalog OPML byte limit exceeded')
    try:
        root = SafeET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, DefusedXmlException, ValueError) as exc:
        raise ValueError('invalid or unsafe catalog OPML') from exc
    if root.tag != 'opml' or len(root.findall('body')) != 1:
        raise ValueError('one OPML body is required')
    stack, count = [(root, 0)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > 16:
            raise ValueError('catalog OPML structure limit exceeded')
        stack.extend((child, depth + 1) for child in node)
    rows, feed_count = {}, 0
    pending = [(node, ()) for node in root.find('body')]
    while pending:
        node, path = pending.pop()
        if node.tag != 'outline':
            raise ValueError('catalog body must contain outlines')
        if 'xmlUrl' not in node.attrib:
            label = text(node.get('text') or node.get('title'), 40)
            folder_path = (*path, label)
            if len(folder_path) > 2 or not any(p[:len(folder_path)] == folder_path for p in PATHS):
                raise ValueError('unknown catalog taxonomy path')
            pending.extend((child, folder_path) for child in node)
            continue
        if path not in PATHS or len(node):
            raise ValueError('feed must be a leaf under section and group')
        feed_count += 1
        if feed_count > MAX_FEEDS:
            raise ValueError('catalog feed limit exceeded')
        url = validate_url(node.get('xmlUrl'))
        name = text(node.get('text') or node.get('title'), 255)
        language = node.get('language', '')
        if not isinstance(language, str) or len(language) > 32 or any(ord(c) < 32 for c in language):
            raise ValueError('invalid catalog language')
        section, group = PATHS[path]
        tags = {catalog_tag(section, group), *path, LEGACY_TAGS[group]}
        key = url_key(url)
        if key in rows:
            rows[key]['tags'] = sorted(set(rows[key]['tags']) | tags)
        else:
            rows[key] = dict(key=hashlib.sha256(key.encode()).hexdigest(), name=name,
                             description='', language=language, region='', tags=sorted(tags),
                             public_url=url, kind='feed', visibility='public',
                             required_parameters=[], capability_requirements=[])
    if not rows:
        raise ValueError('empty catalog OPML')
    result = sorted(rows.values(), key=lambda r: r['key'])
    check_minimum(result, minimum)
    return result


def merge_catalog(existing, incoming, source):
    """Keep all existing stable identities; annotate matches, never resurrect hides."""
    records = copy.deepcopy(list(existing))
    by_url = defaultdict(list)
    for row in records:
        if row.get('verified_at') is not None:
            raise ValueError('runtime verification evidence requires explicit migration')
        if row.get('kind', 'feed') == 'feed':
            by_url[url_key(row['public_url'])].append(row)
    report = dict(incoming=len(incoming), added=0, reused=0, suppressed=0,
                  annotated=0, existing=len(records), suppressed_urls=[])
    for row in sorted(incoming, key=lambda r: r['key']):
        matches = by_url.get(url_key(row['public_url']), [])
        visible = sorted((r for r in matches if r.get('visibility', 'public') == 'public'),
                         key=lambda r: (r['origin']['id'], r['origin']['key']))
        if matches and not visible:
            report['suppressed'] += 1
            report['suppressed_urls'].append(row['public_url'])
            continue
        if visible:
            target = visible[0]
            tags = sorted(set(target['tags']) | set(row['tags']))
            report['annotated'] += tags != sorted(target['tags'])
            target['tags'] = tags
            report['reused'] += 1
        else:
            target = copy.deepcopy(row)
            target['origin'] = {**source, 'key': row['key']}
            records.append(target)
            by_url[url_key(target['public_url'])].append(target)
            report['added'] += 1
    collections = {}
    for row in records:
        origin = {k: row['origin'][k] for k in ('id', 'commit', 'license', 'url')}
        origin_key = json.dumps(origin, sort_keys=True, ensure_ascii=False)
        collection = collections.setdefault(origin_key, {'source': origin, 'entries': []})
        entry = {key: row[key] for key in ENTRY_FIELDS if key in row}
        entry['key'] = row['origin']['key']
        entry['tags'] = sorted(set(entry.get('tags', [])))
        collection['entries'].append(entry)
    ordered = [collections[key] for key in sorted(collections)]
    for collection in ordered:
        collection['entries'].sort(key=lambda row: row['key'])
    report['total_entries'] = len(records)
    report['sections'] = taxonomy_counts(records)
    return {'schema_version': 1, 'source': dict(source), 'collections': ordered}, report


def encode_snapshot(document):
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
