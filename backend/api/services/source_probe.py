"""Bounded source probes that persist metadata only, never response bodies."""
import json
import urllib.request
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from api.models import SourceConfig
from api.services.article_fetcher.safe_http import SafeHTTPStatusError, UnsafeURL, safe_urlopen
from api.services.feed_support import InvalidFeed, parse_feed


class ProbeConflict(RuntimeError):
    pass


def _nested(value, path):
    current = value
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ''


def _allowed_url(value, base_url, allowed_hosts):
    target = urljoin(base_url, _text(value))
    parsed = urlsplit(target)
    if (parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or
            parsed.port not in {None, 80, 443} or parsed.hostname not in allowed_hosts):
        return ''
    return target


def _feed_samples(body, endpoint):
    parsed = parse_feed(body)
    config = endpoint.parser_config
    identity_field = config.get('identity_field', 'id|guid|link')
    title_field = config.get('title_field', 'title')
    link_field = config.get('link_field', 'link')
    published_field = config.get('published_field', 'published|updated')
    samples = []
    for entry in parsed.entries[:3]:
        title = _text(entry.get(title_field) or entry.get('title'))
        link = _allowed_url(entry.get(link_field) or entry.get('link'), endpoint.url, set(endpoint.allowed_domains))
        identity = _text(entry.get(config.get('identity_field', 'id')) or entry.get('guid') or link)
        published = _text(entry.get(config.get('published_field', 'published')) or entry.get('updated'))
        if title and link and identity:
            samples.append({'title': title[:500], 'url': link, 'identity': identity[:200], 'published_at': published[:100]})
    return parsed.version, identity_field, published_field, samples


def _html_samples(body, endpoint):
    soup = BeautifulSoup(body, 'html.parser')
    config = endpoint.parser_config
    nodes = list(soup.select(config['list_item']))
    for script in soup.select('script[type="text/xml"]'):
        markup = (script.string or script.decode_contents()).replace('<![CDATA[', '').replace(']]>', '')
        nodes.extend(BeautifulSoup(markup, 'html.parser').select(config['list_item']))
    samples = []
    for node in nodes[:min(endpoint.max_items, 3)]:
        title_node = node.select_one(config['title'])
        link_node = node.select_one(config['link'])
        date_node = node.select_one(config['date'])
        link = _allowed_url(link_node.get('href') if link_node else '', endpoint.url, set(endpoint.allowed_domains))
        title = title_node.get_text(' ', strip=True) if title_node else ''
        published = date_node.get_text(' ', strip=True) if date_node else ''
        if published and title.endswith(published):
            title = title[:-len(published)].strip()
        if title and link:
            samples.append({'title': title[:500], 'url': link, 'identity': urlsplit(link).path[:200], 'published_at': published[:100]})
    return 'html', 'article URL path', config['date'], samples


def _json_samples(body, endpoint):
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        raise ValueError('invalid_json') from None
    config = endpoint.parser_config
    entries = _nested(payload, config['list_path'])
    if not isinstance(entries, list):
        raise ValueError('invalid_list_path')
    fields = config['fields']
    samples = []
    for entry in entries[:min(endpoint.max_items, 3)]:
        identity = _text(_nested(entry, fields['identity']))
        title = _text(_nested(entry, fields['title']))
        link = _allowed_url(_nested(entry, fields['link']), endpoint.url, set(endpoint.allowed_domains))
        published = _text(_nested(entry, fields['published']))
        if identity and title and link:
            samples.append({'title': title[:500], 'url': link, 'identity': identity[:200], 'published_at': published[:100]})
    return 'json', fields['identity'], fields['published'], samples


def _failure_summary(endpoint, error):
    status = getattr(error, 'http_status', None) or getattr(error, 'code', None)
    code = getattr(error, 'error_code', 'probe_failed')
    blocked = status in {401, 403, 412} or code in {'access_blocked', 'auth_required', 'rate_limited'}
    return ('blocked' if blocked else 'unsupported'), {
        'probed_at': timezone.now().isoformat(),
        'endpoint_id': endpoint.pk,
        'endpoint_kind': endpoint.kind,
        'url': endpoint.url,
        'http_status': status,
        'outcome': 'BLOCKED' if blocked else 'UNSUPPORTED',
        'error_code': code,
    }


def probe_source(config):
    endpoint = config.endpoints.filter(enabled=True).order_by('priority', 'id').first()
    if endpoint is None:
        raise ValueError('missing_endpoint')
    version = config.config_version
    allowed_hosts = frozenset(value.lower().rstrip('.') for value in endpoint.allowed_domains)
    request = urllib.request.Request(endpoint.url, headers={
        'Accept': {
            'rss': 'application/rss+xml, application/xml;q=0.9, text/xml;q=0.8',
            'atom': 'application/atom+xml, application/xml;q=0.9, text/xml;q=0.8',
            'json': 'application/json',
            'html': 'text/html, application/xhtml+xml;q=0.9',
        }[endpoint.kind],
        'User-Agent': 'NewsHubSourceProbe/1.0 (+https://github.com/CoderLambert/news-aggregator)',
    }, method='GET')
    try:
        with safe_urlopen(request, timeout=15, allowed_hosts=allowed_hosts) as response:
            body = response.read()
            content_type = response.headers.get('Content-Type', '')[:200]
            if len(body) > endpoint.max_response_bytes:
                raise ValueError('oversize')
            if endpoint.kind in {'rss', 'atom'}:
                format_name, identity_field, published_field, samples = _feed_samples(body, endpoint)
            elif endpoint.kind == 'html':
                if 'html' not in content_type.lower():
                    raise ValueError('invalid_content_type')
                format_name, identity_field, published_field, samples = _html_samples(body, endpoint)
            else:
                if 'json' not in content_type.lower():
                    raise ValueError('invalid_content_type')
                format_name, identity_field, published_field, samples = _json_samples(body, endpoint)
            if not samples:
                raise ValueError('no_stable_samples')
            effective = response.geturl()
            summary = {
                'probed_at': timezone.now().isoformat(), 'endpoint_id': endpoint.pk,
                'endpoint_kind': endpoint.kind, 'url': endpoint.url,
                'effective_url': effective,
                'redirect_chain': [endpoint.url] if effective == endpoint.url else [endpoint.url, effective],
                'http_status': response.status, 'content_type': content_type,
                'response_bytes': len(body), 'format': format_name,
                'identity_field': identity_field, 'published_field': published_field,
                'sample_articles': samples, 'outcome': 'SUPPORTED',
                'etag_present': bool(response.headers.get('ETag')),
                'last_modified_present': bool(response.headers.get('Last-Modified')),
            }
            new_status, unavailable = 'probed', ''
    except (SafeHTTPStatusError, UnsafeURL, InvalidFeed, ValueError) as error:
        new_status, summary = _failure_summary(endpoint, error)
        unavailable = summary['error_code']

    with transaction.atomic():
        current = SourceConfig.objects.select_for_update().get(pk=config.pk)
        if current.config_version != version:
            raise ProbeConflict('configuration_changed')
        current.status = new_status
        current.probe_summary = summary
        current.probed_config_version = version if new_status == 'probed' else None
        current.probed_at = timezone.now()
        current.approved_config_version = None
        current.approved_by = None
        current.approved_at = None
        current.unavailable_reason = unavailable
        current.save(update_fields=[
            'status', 'probe_summary', 'probed_config_version', 'probed_at',
            'approved_config_version', 'approved_by', 'approved_at',
            'unavailable_reason', 'updated_at',
        ])
    return current
