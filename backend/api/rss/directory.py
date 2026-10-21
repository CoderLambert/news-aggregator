"""Bounded, offline directory snapshots. No feed requests or subscription writes.

The caller supplies reviewed bytes plus their pinned SHA256, and schedules checks
once per day. A failed validation/write leaves the previous active snapshot intact.
"""

import hashlib
import ipaddress
import json
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from django.core import signing
from django.db import transaction

from .directory_models import FeedDirectoryEntry, FeedDirectorySnapshot

SCHEMA_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10000
ENTRY_NAMESPACE = uuid.UUID('58b71826-b704-480a-b18e-e94b055acdf5')
SEED_PATH = Path(__file__).with_name('directory_data') / 'seed-v1.json'


class DirectoryValidationError(ValueError):
    pass


class DirectoryCursorError(ValueError):
    pass


def _text(value, field, maximum=255, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise DirectoryValidationError(f'invalid {field}')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise DirectoryValidationError(f'invalid {field}')
    return value


def _strings(value, field, maximum=64):
    if not isinstance(value, list) or len(value) > maximum:
        raise DirectoryValidationError(f'invalid {field}')
    return sorted({_text(item, field, 128) for item in value})


def _object(value, field):
    if not isinstance(value, dict):
        raise DirectoryValidationError(f'invalid {field}')
    return value


def _public_url(value):
    value = _text(value, 'public_url', 1024)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        if (parsed.scheme != 'https' or not host or parsed.username is not None
                or parsed.password is not None or port not in (None, 443)
                or parsed.fragment or '%' in parsed.netloc
                or re.search(r'\s|\\', value)):
            raise ValueError
        if any(re.search(r'token|secret|password|api.?key|auth|cookie', key, re.I)
               for key, _ in parse_qsl(parsed.query)):
            raise ValueError
        if host.lower() == 'localhost' or '.' not in host or host.endswith(('.local', '.internal')):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
    except ValueError:
        raise DirectoryValidationError('invalid public HTTPS URL') from None
    # This is metadata validation, not DNS/SSRF approval for subscribing.
    return value


def _source(value):
    value = _object(value, 'source')
    commit = _text(value.get('commit'), 'source.commit', 64)
    if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', commit):
        raise DirectoryValidationError('source.commit must be pinned')
    return {
        'id': _text(value.get('id'), 'source.id', 128),
        'commit': commit,
        'license': _text(value.get('license'), 'source.license', 128),
        'url': _public_url(value.get('url')),
    }


def _entry(row, source):
    row = _object(row, 'entry')
    key = _text(row.get('key'), 'entry.key', 256)
    kind = row.get('kind', 'feed')
    if kind not in ('feed', 'route_template'):
        raise DirectoryValidationError('invalid entry.kind')
    visibility = row.get('visibility', 'public')
    if visibility not in ('public', 'hidden'):
        raise DirectoryValidationError('personal entries cannot be published')
    parameters = _strings(row.get('required_parameters', []), 'required_parameters')
    capabilities = _strings(row.get('capability_requirements', []), 'capability_requirements')
    if kind == 'feed' and (parameters or capabilities):
        raise DirectoryValidationError('unresolved requirements must be templates')
    if kind == 'route_template':
        url = _text(row.get('public_url'), 'route template', 1024)
        if not re.fullmatch(r'/[a-zA-Z0-9_/:?*.-]+', url) or '..' in url:
            raise DirectoryValidationError('unsupported route path syntax')
    else:
        url = _public_url(row.get('public_url'))
    if kind == 'feed' and re.search(r'[:*{}]', urlsplit(url).path):
        raise DirectoryValidationError('template cannot be a feed')
    # Catalog imports carry no health evidence: never promote imported timestamps.
    if row.get('verified_at') is not None:
        raise DirectoryValidationError('catalog metadata is not verification evidence')
    return {
        'entry_id': uuid.uuid5(ENTRY_NAMESPACE, source['id'] + ':' + key),
        'name': _text(row.get('name'), 'name'),
        'description': _text(row.get('description', ''), 'description', 16384, empty=True),
        'language': _text(row.get('language', ''), 'language', 32, empty=True),
        'region': _text(row.get('region', ''), 'region', 32, empty=True),
        'tags': _strings(row.get('tags', []), 'tags'),
        'origin': {**source, 'key': key},
        'kind': kind, 'public_url': url,
        'required_parameters': parameters, 'capability_requirements': capabilities,
        'verified_at': None, 'visibility': visibility,
    }


def _rsshub_entries(namespaces, source):
    """Read pinned RSSHub routes.json namespace/route metadata; never TS/JS.

    Only these declarative fields are consumed. Radar/handlers/heat/topFeeds are
    deliberately ignored. No example route is promoted to a concrete feed.
    """
    for namespace, metadata in _object(namespaces, 'namespaces').items():
        if not isinstance(namespace, str) or not re.fullmatch(r'[a-z0-9_-]+', namespace):
            raise DirectoryValidationError('invalid namespace')
        metadata = _object(metadata, 'namespace metadata')
        namespace_name = _text(metadata.get('name'), 'namespace.name')
        routes = metadata.get('routes')
        if not isinstance(routes, dict):
            raise DirectoryValidationError('routes must be an object keyed by route path')
        for route_key, route in routes.items():
            route = _object(route, 'route')
            if not isinstance(route_key, str) or not route_key.startswith('/'):
                raise DirectoryValidationError('invalid namespace route key')
            paths = route.get('path')
            paths = [paths] if isinstance(paths, str) else paths
            if not isinstance(paths, list) or not paths:
                raise DirectoryValidationError('invalid route.path')
            parameters = _object(route.get('parameters', {}), 'route.parameters')
            for name, definition in parameters.items():
                _text(name, 'parameter name', 128)
                if isinstance(definition, str):
                    _text(definition, 'parameter description', 4096, empty=True)
                else:
                    definition = _object(definition, 'parameter definition')
                    _text(definition.get('description'), 'parameter description', 4096, empty=True)
            features = _object(route.get('features', {}), 'features')
            capabilities = []
            configs = features.get('requireConfig', [])
            if configs is False:
                configs = []
            if not isinstance(configs, list):
                raise DirectoryValidationError('invalid requireConfig')
            for config in configs:
                config = _object(config, 'requireConfig item')
                if config.get('optional') is not True:
                    capabilities.append('config:' + _text(config.get('name'), 'config name', 100))
            for feature in ('requirePuppeteer', 'antiCrawler', 'supportScihub'):
                if features.get(feature):
                    capabilities.append(feature)
            for path in paths:
                path = _text(path, 'route.path', 900)
                if not re.fullmatch(r'/[a-zA-Z0-9_/:?*.-]*', path) or '..' in path:
                    raise DirectoryValidationError('unsupported route path syntax')
                required = [name for name, optional in re.findall(r':([a-zA-Z0-9_]+)(\??)', path) if not optional]
                if any(name not in parameters for name in required):
                    raise DirectoryValidationError('missing route parameter declaration')
                # '?' is route syntax, not an actual URL query.
                template = '/' + namespace + path
                row = {
                    'key': template, 'name': namespace_name + ' · ' + _text(route.get('name'), 'route.name'),
                    'description': route.get('description', metadata.get('description', '')),
                    'language': metadata.get('lang', ''),
                    'tags': route.get('categories', metadata.get('categories', [])),
                    'kind': 'route_template', 'public_url': template,
                    'required_parameters': required, 'capability_requirements': capabilities,
                }
                yield _entry(row, source)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DirectoryValidationError('duplicate JSON key')
        result[key] = value
    return result


def import_snapshot(payload, *, expected_checksum):
    """Validate pinned UTF-8 JSON bytes, then activate all entries atomically.

    Optional collections contain additional independently attributed sources; all
    collections are validated and swapped together. No implicit merging with the
    previous snapshot or user sources occurs.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
        raise DirectoryValidationError('snapshot byte limit exceeded')
    checksum = hashlib.sha256(payload).hexdigest()
    if checksum != expected_checksum:
        raise DirectoryValidationError('checksum mismatch')
    try:
        document = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise DirectoryValidationError('invalid snapshot JSON') from exc
    document = _object(document, 'snapshot')
    if type(document.get('schema_version')) is not int or document['schema_version'] != SCHEMA_VERSION:
        raise DirectoryValidationError('unsupported schema_version')
    source = _source(document.get('source'))
    if sum(field in document for field in ('entries', 'namespaces', 'collections')) != 1:
        raise DirectoryValidationError('ambiguous snapshot format')
    collections = document.get('collections', [document])
    if not isinstance(collections, list) or not collections or len(collections) > 100:
        raise DirectoryValidationError('invalid collections')
    validated, seen, origins = [], set(), []
    for collection in collections:
        collection = _object(collection, 'collection')
        origin = _source(collection.get('source'))
        origins.append(origin)
        if 'entries' in collection and 'namespaces' in collection:
            raise DirectoryValidationError('ambiguous snapshot format')
        if 'namespaces' in collection:
            rows = _rsshub_entries(collection['namespaces'], origin)
        else:
            entries = collection.get('entries')
            if not isinstance(entries, list):
                raise DirectoryValidationError('entries must be a list')
            rows = (_entry(row, origin) for row in entries)
        for row in rows:
            if row['entry_id'] in seen:
                raise DirectoryValidationError('duplicate stable entry ID')
            seen.add(row['entry_id'])
            validated.append(row)
            if len(validated) > MAX_ENTRIES:
                raise DirectoryValidationError('entry limit exceeded')
    if not validated:
        raise DirectoryValidationError('empty snapshot')
    with transaction.atomic():
        # SQLite serializes this first write. The DB constraint also prevents two
        # simultaneous publishers from leaving more than one active snapshot.
        FeedDirectorySnapshot.objects.filter(active=True).update(active=False)
        snapshot, created = FeedDirectorySnapshot.objects.get_or_create(
            checksum=checksum,
            defaults={'commit': source['commit'], 'license': source['license'],
                      'schema_version': SCHEMA_VERSION, 'provenance': {'bundle': source, 'sources': origins}},
        )
        if created:
            FeedDirectoryEntry.objects.bulk_create([
                FeedDirectoryEntry(snapshot=snapshot, **row) for row in validated
            ])
        snapshot.active = True
        snapshot.save(update_fields=['active'])
    return snapshot


def import_pinned_seed():
    lock = json.loads(SEED_PATH.with_suffix('.lock.json').read_text())
    return import_snapshot(SEED_PATH.read_bytes(), expected_checksum=lock['sha256'])


def _fold(value):
    return unicodedata.normalize('NFKC', value).casefold().strip()


# Reviewed display groups over the pinned directory tags; no model inference.
DIRECTORY_CATEGORIES = (
    ('ai', '人工智能', ('Artificial Intelligence',)),
    ('engineering', '编程与技术', ('Engineering & Technology',)),
    ('security', '网络安全', ('Security',)),
    ('news', '科技与资讯', ('Technology Media', 'Tech Newsletters & Weeklies', 'News')),
    ('science', '科学研究', ('Research & Science',)),
    ('design', '产品与设计', ('Product & Design',)),
    ('business', '商业与创业', ('Business & Startups',)),
    ('culture', '人文与博客', ('Personal Blogs', 'Culture & Ideas')),
    ('community', '社区与播客', ('Communities', 'Podcasts', 'Videos')),
)
FEATURED_CHANNELS = frozenset({
    'OpenAI News', '机器之心', 'Hugging Face - Blog', 'Google DeepMind News',
    'Martin Fowler', 'The GitHub Blog', '阮一峰的网络日志', '少数派', 'WIRED',
    'CISA', 'Krebs on Security', 'Nature', 'NASA', 'Quanta Magazine',
    '阿里云设计中心', '拾月的博客', '虹线', 'Macin', '卢昌海个人主页',
    'Hacker News', 'V2EX · 技术', '硅谷101 — Podcast',
})


def directory_category_ids(tags):
    return {key for key, _label, names in DIRECTORY_CATEGORIES
            if any(tag.endswith(name) for tag in tags for name in names)}


def search_directory(q='', *, limit=20, cursor=None, category=''):
    """Return local metadata only; T20 adds authorized user state/previews.

    `subscribed=None` means unknown until user-aware enrichment. Empty cached
    articles carry no invented preview or statistics. Cursor binds query/version.
    """
    if not isinstance(q, str) or len(q) > 200:
        raise DirectoryValidationError('query must be at most 200 characters')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise DirectoryValidationError('limit must be between 1 and 50')
    if category not in {'', *(row[0] for row in DIRECTORY_CATEGORIES)}:
        raise DirectoryValidationError('invalid category')
    query = _fold(q)
    snapshot = FeedDirectorySnapshot.objects.filter(active=True).first()
    version = snapshot.checksum if snapshot else None
    offset = 0
    if cursor:
        try:
            state = signing.loads(cursor, salt='rss-directory-v1', max_age=86400)
            if state['snapshot'] != version or state['query'] != query or state.get('category', '') != category or state.get('order_version') != 2:
                raise ValueError
            offset = state['offset']
            if type(offset) is not int or offset < 0 or offset > MAX_ENTRIES:
                raise ValueError
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            raise DirectoryCursorError('invalid or stale directory cursor') from None
    matches = []
    if snapshot:
        for entry in snapshot.entries.filter(visibility='public'):
            if category and category not in directory_category_ids(entry.tags):
                continue
            name, url = _fold(entry.name), _fold(entry.public_url)
            if not query or query in (name, url):
                rank = 0
            elif name.startswith(query) or url.startswith(query):
                rank = 1
            elif any(query in value for value in [name, url, _fold(entry.description), *map(_fold, entry.tags)]):
                rank = 2
            else:
                continue
            matches.append(((rank, entry.name not in FEATURED_CHANNELS, entry.kind != 'feed', name, str(entry.entry_id)), entry))
    matches.sort(key=lambda match: match[0])
    page = matches[offset:offset + limit]
    fields = ('name', 'description', 'language', 'region', 'tags', 'origin', 'kind',
              'public_url', 'required_parameters', 'capability_requirements', 'verified_at')
    results = [dict(id=str(entry.entry_id), **{field: getattr(entry, field) for field in fields},
                    subscribed=None, cached_articles=[], recommended=entry.name in FEATURED_CHANNELS) for _, entry in page]
    next_cursor = None
    if offset + limit < len(matches):
        next_cursor = signing.dumps({'snapshot': version, 'query': query, 'category': category, 'order_version': 2, 'offset': offset + limit},
                                    salt='rss-directory-v1', compress=True)
    return {'results': results, 'next_cursor': next_cursor, 'snapshot_version': version,
            'categories': [{'id': key, 'name': label} for key, label, _tags in DIRECTORY_CATEGORIES]}
