"""Publisher identity and body contracts shared by spiders and Providers."""
from urllib.parse import urlsplit

from api.services.article_identity import InvalidIdentity, normalize_article_url, validate_upstream_id
from api.services.article_fetcher.types import FullContentCandidate
from api.services.source_dates import parse_source_datetime


def dev_article_item(payload, *, classify=None):
    if not isinstance(payload, dict) or isinstance(payload.get('id'), bool):
        raise InvalidIdentity('invalid_identity')
    identity = validate_upstream_id(str(payload.get('id', '')))
    if not identity.isdecimal() or int(identity) <= 0:
        raise InvalidIdentity('invalid_identity')
    target = normalize_article_url(payload.get('url', ''))
    if urlsplit(target).hostname != 'dev.to' or not payload.get('title'):
        raise InvalidIdentity('invalid_identity')
    published = parse_source_datetime(payload.get('published_at'))
    modified = parse_source_datetime(payload.get('edited_at'))
    user = payload.get('user') or {}
    tags = payload.get('tag_list') or []
    if isinstance(tags, str):
        tags = tags.split(',')
    summary = payload.get('description') or ''
    item = dict(source_key='devto', source_name='Dev.to', upstream_id=identity,
                title=payload['title'], url=target, discovery_url=target, content_kind='article',
                summary=summary, content=summary, author=user.get('name') or user.get('username') or '',
                cover_image=payload.get('cover_image') or '', publish_time=published,
                publish_time_inferred=published is None,
                category_name=classify(payload['title'], summary + ' ' + ' '.join(tags)) if classify else '科技')
    if modified:
        item['source_modified_at'] = modified
    return item


def dev_candidate(payload, *, target_url, retrieved_from_url, request_started_at,
                  source_item_id=None, expected_revision=None):
    item = dev_article_item(payload)
    if item['url'] != normalize_article_url(target_url) or (source_item_id and item['upstream_id'] != source_item_id):
        raise InvalidIdentity('invalid_identity')
    field = 'body_markdown' if payload.get('body_markdown') else 'body_html'
    body = payload.get(field)
    if not isinstance(body, str) or not body.strip():
        raise ValueError('body_partial')
    return FullContentCandidate(
        'devto', item['upstream_id'], item['url'], retrieved_from_url,
        payload.get('canonical_url') or None, item['title'], 'article', field,
        'markdown' if field == 'body_markdown' else 'html', 'full', body,
        parse_source_datetime(payload.get('edited_at')), None, request_started_at,
        expected_revision=expected_revision,
    )


def hn_candidate(payload, *, target_url, retrieved_from_url, request_started_at, source_item_id=None):
    if (not isinstance(payload, dict) or payload.get('type') != 'story' or payload.get('deleted') or
            payload.get('dead') or payload.get('url') or isinstance(payload.get('id'), bool)):
        raise InvalidIdentity('invalid_identity')
    identity = str(payload.get('id', ''))
    if not identity.isdecimal() or (source_item_id and source_item_id != identity):
        raise InvalidIdentity('invalid_identity')
    return FullContentCandidate(
        'hackernews', identity, target_url, retrieved_from_url, None, payload.get('title') or '',
        'discussion', 'text', 'html', 'full', payload.get('text') or '', None, None, request_started_at,
    )
