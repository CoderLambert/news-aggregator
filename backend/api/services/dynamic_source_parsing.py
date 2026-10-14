"""Pure, bounded parsers for administrator-maintained JSON and HTML lists."""
import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from api.services.article_identity import normalize_article_url, validate_upstream_id
from api.services.source_dates import parse_feed_datetime
from api.services.source_policy import policy_for_key


class InvalidDynamicPayload(ValueError):
    error_code = 'invalid_dynamic_payload'


def nested(value, path):
    current = value
    for part in str(path or '').split('.'):
        if not part or not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def scalar(value):
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ''


def allowed_url(value, base_url, allowed_domains, *, require_article=True):
    raw = scalar(value)
    if not raw:
        return ''
    target = urljoin(base_url, raw)
    try:
        target = normalize_article_url(target, max_length=1024, require_article=require_article)
    except ValueError:
        return ''
    return target if urlsplit(target).hostname in set(allowed_domains) else ''


def parse_json_list(body, endpoint):
    if not isinstance(body, bytes) or len(body) > endpoint['max_response_bytes']:
        raise InvalidDynamicPayload('oversize')
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        raise InvalidDynamicPayload('invalid_json') from None
    config = endpoint['parser_config']
    rows = nested(payload, config['list_path'])
    if not isinstance(rows, list):
        raise InvalidDynamicPayload('invalid_list_path')
    fields = config['fields']
    entries = []
    for row in rows[:endpoint['max_items']]:
        if not isinstance(row, dict):
            entries.append({})
            continue
        entries.append({name: scalar(nested(row, path)) for name, path in fields.items()})
    next_url = allowed_url(nested(payload, config.get('next_path')), endpoint['url'],
                           endpoint['allowed_domains'], require_article=False) if config.get('next_path') else ''
    return entries, next_url


def _node_text(node, selector):
    selected = node.select_one(selector) if selector else None
    return selected.get_text(' ', strip=True) if selected else ''


def parse_html_list(body, endpoint):
    if not isinstance(body, bytes) or len(body) > endpoint['max_response_bytes']:
        raise InvalidDynamicPayload('oversize')
    config = endpoint['parser_config']
    soup = BeautifulSoup(body, 'html.parser')
    nodes = list(soup.select(config['list_item']))
    # Some government CMS pages embed a declarative XML datastore in a
    # non-executable script element. Parse that inert markup, never JavaScript.
    for script in soup.select('script[type="text/xml"]'):
        markup = (script.string or script.decode_contents()).replace('<![CDATA[', '').replace(']]>', '')
        embedded = BeautifulSoup(markup, 'html.parser')
        nodes.extend(embedded.select(config['list_item']))
    entries = []
    for node in nodes[:endpoint['max_items']]:
        link_node = node.select_one(config['link'])
        href = link_node.get('href', '') if link_node else ''
        link = allowed_url(href, endpoint['url'], endpoint['allowed_domains'])
        title = _node_text(node, config['title'])
        published = _node_text(node, config['date'])
        if published and title.endswith(published):
            title = title[:-len(published)].strip()
        entries.append({
            'identity': link,
            'title': title,
            'link': link,
            'summary': _node_text(node, config.get('summary')),
            'published': published,
            'content': _node_text(node, config.get('content')),
        })
    next_node = soup.select_one(config['next']) if config.get('next') else None
    next_url = allowed_url(next_node.get('href', '') if next_node else '', endpoint['url'],
                           endpoint['allowed_domains'], require_article=False)
    return entries, next_url


def structured_entry_item(entry, source_key, endpoint):
    policy = policy_for_key(source_key)
    if policy is None:
        raise ValueError('unknown_source')
    title = scalar(entry.get('title'))
    target = allowed_url(entry.get('link'), endpoint['url'], endpoint['allowed_domains'])
    identity = validate_upstream_id(scalar(entry.get('identity')) or target)
    if not title or not target:
        raise ValueError('invalid_identity')
    published, inferred = parse_feed_datetime(scalar(entry.get('published')), policy)
    summary = scalar(entry.get('summary'))[:3000] if policy.summary_allowed else ''
    return {
        'source_key': source_key,
        'upstream_id': identity,
        'discovery_url': target,
        'content_kind': policy.content_kind,
        'title': title[:500],
        'summary': summary,
        'content': summary,
        'source_name': policy.name,
        'category_name': policy.default_category or '医疗健康',
        'publish_time': published,
        'publish_time_inferred': published is None or inferred,
        'author': scalar(entry.get('author'))[:200],
        'url': target,
        'cover_image': allowed_url(entry.get('image'), endpoint['url'], endpoint['allowed_domains'],
                                   require_article=False),
        'publisher_name': policy.description.split(' · ', 1)[0],
        'channel_name': policy.name,
        'endpoint_kind': endpoint['kind'],
        'endpoint_url': endpoint['url'],
    }
