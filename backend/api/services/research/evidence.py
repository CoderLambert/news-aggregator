"""Bounded provenance ledger for clickable research citations; never an HTTP fetch."""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

_MARKDOWN_LINK = re.compile(r'(?<!!)\[([^\]\n]{1,180})\]\(([^)\s\n]{1,2048})\)')
_BARE_URL = re.compile(r'https?://[^\s<>\]\)]+')
_LOCAL_ARTICLE = re.compile(r'^/news/[1-9][0-9]*$')
_MAX_LINKS = 160


def safe_public_evidence_url(value: object) -> str | None:
    """Validate a display-only URL without DNS/network or authority escalation."""
    if not isinstance(value, str) or not value or len(value) > 2048 or value != value.strip():
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower().rstrip('.')
        if parts.scheme not in {'http', 'https'} or not host or parts.username is not None or parts.password is not None:
            return None
        if any(c in value for c in ('\\', '\r', '\n', '\t')) or '#' in value:
            return None
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.localhost', '.local', '.internal')):
            return None
        if '.' not in host or parts.port not in (None, 80, 443):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return value
    except (ValueError, UnicodeError):
        return None


def _article_link(value: object) -> str | None:
    if type(value) is not int or value <= 0:
        return None
    return f'/news/{value}'


def evidence_links_for_tool(name: str, result: object) -> set[str]:
    """Only links in actual structured tool results are eligible for citation."""
    if not isinstance(result, dict):
        return set()
    links: set[str] = set()
    items = []
    if name in {'search_news', 'analyze_topic', 'fetch_article'}:
        if name == 'fetch_article':
            items.append(result)
        values = result.get('articles')
        if isinstance(values, list):
            items.extend(values[:_MAX_LINKS])
    if name in {'search_web', 'fetch_webpage'}:
        if name == 'fetch_webpage':
            items.append(result)
        values = result.get('results')
        if isinstance(values, list):
            items.extend(values[:_MAX_LINKS])
    for entry in items:
        if not isinstance(entry, dict):
            continue
        url = safe_public_evidence_url(entry.get('url'))
        if url:
            links.add(url)
        if name in {'search_news', 'analyze_topic', 'fetch_article'}:
            local = _article_link(entry.get('id'))
            if local:
                links.add(local)
        if len(links) >= _MAX_LINKS:
            break
    return links


def history_evidence_links(messages: list) -> set[str]:
    """Validate persisted tool outcomes against preceding assistant tool-call IDs."""
    names: dict[str, str] = {}
    links: set[str] = set()
    allowed = {'search_news', 'analyze_topic', 'fetch_article', 'search_web', 'fetch_webpage'}
    for message in messages[-60:]:
        if not isinstance(message, dict):
            continue
        if message.get('role') == 'assistant':
            calls = message.get('tool_calls')
            if not isinstance(calls, list):
                continue
            for call in calls[:20]:
                if not isinstance(call, dict):
                    continue
                fn = call.get('function')
                name = fn.get('name') if isinstance(fn, dict) else None
                call_id = call.get('id')
                if isinstance(call_id, str) and isinstance(name, str) and name in allowed:
                    names[call_id] = name
            continue
        if message.get('role') != 'tool':
            continue
        name = names.get(message.get('tool_call_id'))
        if name not in allowed:
            continue
        raw = message.get('content')
        if not isinstance(raw, str) or len(raw) > 35000:
            continue
        try:
            result = json.loads(raw)
        except (ValueError, TypeError):
            continue
        links.update(evidence_links_for_tool(name, result))
        if len(links) >= _MAX_LINKS:
            return set(sorted(links)[:_MAX_LINKS])
    return links


def scrub_unverified_links(text: str, evidence_links: set[str]) -> str:
    """Do not publish model-invented clickable markdown links as verified citations."""
    if not isinstance(text, str):
        return ''
    def replace(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if url in evidence_links and (safe_public_evidence_url(url) or _LOCAL_ARTICLE.fullmatch(url)):
            return match.group(0)
        return f'{label}（来源链接未经验证）'
    sanitized = _MARKDOWN_LINK.sub(replace, text)
    # Bare URLs may also become clickable in Markdown (GFM autolink).
    return _BARE_URL.sub(
        lambda match: match.group(0) if match.group(0) in evidence_links else '[未验证外部链接]',
        sanitized,
    )
