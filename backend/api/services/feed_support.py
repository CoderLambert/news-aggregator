"""Pure Feed parsing: bytes in, bounded metadata and typed candidates out."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import feedparser

from api.services.article_identity import normalize_article_url, validate_upstream_id
from api.services.article_fetcher.types import FullContentCandidate
from api.services.article_fetcher.extractors import html_fragment_to_markdown
from api.services.source_policy import POLICIES

MAX_FEED_BYTES = 8 * 1024 * 1024


class InvalidFeed(ValueError):
    error_code = 'invalid_feed'


def parse_source_datetime(value, *, assume_utc=False):
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str) or not value.strip():
        return None
    else:
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value.strip())
            except (TypeError, ValueError, OverflowError):
                return None
    if parsed.tzinfo is None:
        if not assume_utc:
            return None
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ParsedFeed:
    entries: tuple
    version: str


def parse_feed(body: bytes):
    if not isinstance(body, bytes) or len(body) > MAX_FEED_BYTES:
        raise InvalidFeed('oversize')
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise InvalidFeed('invalid_feed') from None
    tag = root.tag.rsplit('}', 1)[-1].lower()
    if tag not in {'rss', 'feed', 'rdf'}:
        raise InvalidFeed('invalid_feed')
    if tag == 'rss' and not any(child.tag.rsplit('}', 1)[-1].lower() == 'channel' for child in root):
        raise InvalidFeed('invalid_feed')
    # Never pass a URL or a str to feedparser: it must not fetch independently.
    result = feedparser.parse(body)
    if result.bozo or not result.version.startswith(('rss', 'atom')):
        raise InvalidFeed('invalid_feed')
    return ParsedFeed(tuple(result.entries), result.version)


def _plain(value):
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)


def _excerpt(markdown):
    for paragraph in markdown.split('\n\n'):
        text = paragraph.strip()
        if text and not text.startswith(('#', '```', '![', '|')):
            return text[:500]
    return markdown[:500]


def feed_entry_item(entry, source_key, *, feed_url, effective_url, request_started_at, version,
                    request_chain=(), classify=None):
    policy = POLICIES[source_key]
    title = _plain(entry.get('title', '')).strip()
    target = normalize_article_url(entry.get('link', ''))
    identity = validate_upstream_id(entry.get('id') or entry.get('guid') or target)
    published = parse_source_datetime(dict.get(entry, 'published'))
    modified = parse_source_datetime(dict.get(entry, 'updated'))
    summary_html = entry.get('summary', '') or ''
    body = field = ''
    body_format = 'html'
    if 'description' in policy.body_fields and summary_html:
        body, field = summary_html, 'description'
    elif version.startswith('atom') and 'atom:content' in policy.body_fields:
        for content in entry.get('content', ()):
            if content.get('type') in {'text/html', 'application/xhtml+xml', 'text/plain'}:
                body, field = content.get('value', ''), 'atom:content'
                body_format = 'text' if content.get('type') == 'text/plain' else 'html'
                break
    elif 'content:encoded' in policy.body_fields:
        for content in entry.get('content', ()):
            if content.get('type') in {'text/html', 'application/xhtml+xml'}:
                body, field = content.get('value', ''), 'content:encoded'
                break
    # media_content is intentionally never considered an article body.
    summary = _plain(summary_html)[:3000] if field != 'description' else ''
    candidate = None
    if body:
        candidate = FullContentCandidate(
            source_key, identity, target, effective_url, None, title, policy.content_kind,
            field, body_format, 'full', body, modified, None, request_started_at,
            request_chain=tuple(request_chain),
        )
        if not summary:
            summary = _excerpt(html_fragment_to_markdown(body, target) if body_format == 'html' else body)
    if not title:
        raise ValueError('invalid_identity')
    image = next((link.get('href') for link in entry.get('links', ()) if link.get('rel') == 'enclosure' and
                  str(link.get('type', '')).startswith('image/')), '')
    item = dict(source_key=source_key, upstream_id=identity, discovery_url=target,
                content_kind=policy.content_kind, title=title, summary=summary, content=summary,
                source_name=policy.name, category_name=classify(title, summary) if classify else '科技',
                publish_time=published, publish_time_inferred=published is None,
                author=entry.get('author', '') or '', url=target, cover_image=image or '')
    if modified:
        item['source_modified_at'] = modified
    if candidate:
        item['body_candidate'] = candidate
    return item
