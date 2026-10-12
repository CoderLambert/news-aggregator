from __future__ import annotations

import html as html_lib
import os
from contextvars import ContextVar
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from django.conf import settings

from api.services.content_cleaner import clean_content

from .extractors import extract_markdown_from_html, html_fragment_to_markdown
from .safe_http import safe_urlopen
from .site_rules import get_site_rule, normalize_domain
from .types import FetchResult, FullContentCandidate, transport_failure
from api.services.request_budget import BudgetDeferred
from .execution import ExecutionStopped
from .validators import validate_markdown, validate_candidate
from api.services.article_identity import normalize_article_url, InvalidIdentity
from api.services.structured_articles import dev_candidate, hn_candidate
from django.utils import timezone


def _candidate_result(candidate, provider, *, expected_title=None, summary=None):
    validation = validate_candidate(candidate, expected_url=candidate.target_url,
                                    expected_title=expected_title or candidate.title, summary=summary)
    return FetchResult(validation.ok, provider, url=candidate.target_url, title=candidate.title,
                       canonical_url=candidate.declared_canonical_url or '', markdown=validation.markdown,
                       quality_score=validation.score, candidate=candidate if validation.ok else None,
                       error='' if validation.ok else 'validation_failed:' + validation.error_code,
                       error_code='' if validation.ok else validation.error_code,
                       validation_reasons=[] if validation.ok else [validation.error_code], extractor=provider)


class DevToAPIProvider:
    name = 'devto_api'

    def __init__(self, timeout=12):
        self.timeout = timeout

    def fetch(self, url, expected_title=None, summary=None, news=None):
        parsed = urlparse(url)
        if parsed.hostname != 'dev.to':
            return FetchResult(False, self.name, url=url, error='not_devto_article')
        identity = None
        if news is not None:
            from api.models import NewsSourceItem
            identity = NewsSourceItem.objects.filter(news_id=news.pk, source_key='devto').values_list('upstream_id', flat=True).first()
        path = parsed.path.strip('/').split('/')
        if identity and identity.isdecimal():
            api_url = f'https://dev.to/api/articles/{identity}'
        elif len(path) == 2 and all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in path):
            api_url = f'https://dev.to/api/articles/{path[0]}/{path[1]}'
        else:
            return FetchResult(False, self.name, url=url, error='invalid_identity', error_code='invalid_identity')
        started = timezone.now()
        try:
            with _open_url(urllib.request.Request(api_url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT}), timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (BudgetDeferred, ExecutionStopped):
            raise
        except Exception as error:
            return transport_failure(error, provider=self.name, url=url)
        try:
            # The documented path endpoint resolves the authoritative numeric ID.
            # Its candidate records the exact path that supplied the payload.
            candidate = dev_candidate(payload, target_url=url, retrieved_from_url=api_url,
                                      request_started_at=started, source_item_id=identity)
            return _candidate_result(candidate, self.name, expected_title=expected_title, summary=summary)
        except (InvalidIdentity, ValueError, TypeError):
            return FetchResult(False, self.name, url=url, error='invalid_identity', error_code='invalid_identity')
        except Exception as error:
            return transport_failure(error, provider=self.name, url=url)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
LEIPHONE_FEED_USER_AGENT = 'curl/8.0.0'
DEFAULT_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


_research_fetch_guard = ContextVar('research_article_fetch_guard', default=None)


def _open_url(request, timeout, context=None):
    """Every actual news request uses pinned transport and shared admission."""
    guard = _research_fetch_guard.get()
    if guard is not None:
        guard()
    return safe_urlopen(request, timeout=timeout)


class GitHubReadmeProvider:
    """Fetch repository README as raw Markdown for GitHub repo URLs.

    Extracting GitHub's rendered HTML can split highlighted code into many
    token lines. Raw README Markdown preserves fenced code blocks exactly.
    """

    name = 'github_readme'

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None, news=None) -> FetchResult:
        repo = _github_repo_path(url)
        if not repo:
            return FetchResult(ok=False, provider=self.name, url=url, error='not_github_repo')
        owner, name = repo
        title = expected_title or f'{owner}/{name}'
        paths = _github_readme_urls(owner, name)
        preferred = (news.full_content_provenance or {}).get('retrieved_from_url') if news is not None else None
        if preferred:
            # A stored path is only a hint; rerun the exact repository contract.
            probe = FullContentCandidate('github', f'{owner}/{name}', url, preferred, None, title,
                'readme', 'readme', 'markdown', 'full', 'body', None, None, timezone.now())
            from api.services.source_policy import candidate_contract_allows
            if candidate_contract_allows(probe):
                paths = [preferred, *[path for path in paths if path != preferred]]
        for readme_url in paths:
            started = timezone.now()
            try:
                markdown = self._download(readme_url)
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    return transport_failure(error, provider=self.name, url=url)
                continue
            except (BudgetDeferred, ExecutionStopped):
                raise
            except Exception as error:
                return transport_failure(error, provider=self.name, url=url)
            candidate = FullContentCandidate('github', f'{owner}/{name}', normalize_article_url(url),
                readme_url, None, title, 'readme', 'readme', 'markdown', 'full', markdown,
                None, None, started)
            return _candidate_result(candidate, self.name, expected_title=expected_title, summary=summary)
        return FetchResult(False, self.name, url=url, error='readme_not_found', error_code='not_found')

    def _download(self, url: str) -> str:
        req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, 'Accept': 'text/plain,*/*;q=0.8'})
        with _open_url(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read()
            content_type = resp.headers.get('content-type', '')
        encoding = _encoding_from_content_type(content_type) or 'utf-8'
        return raw.decode(encoding, errors='replace')


class HackerNewsAPIProvider:
    """Fetch Hacker News self-post text from the official Firebase API.

    HN is usually an aggregator: external-link stories should be fetched from
    their original URL, not from the HN discussion page. This provider only
    handles `news.ycombinator.com/item?id=...` self posts with `text` content
    and deliberately skips external-link stories so the rest of the provider
    chain can target the real article URL.
    """

    name = 'hackernews_api'

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        item_id = _hackernews_item_id(url)
        if not item_id:
            return FetchResult(ok=False, provider=self.name, url=url, error='not_hackernews_item')

        api_url = f'https://hacker-news.firebaseio.com/v0/item/{item_id}.json'
        started = timezone.now()
        try:
            req = urllib.request.Request(api_url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
            with _open_url(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='replace') or '{}')
        except (BudgetDeferred, ExecutionStopped):
            raise
        except Exception as exc:
            return transport_failure(exc, provider=self.name, url=url)

        if (not isinstance(payload, dict) or payload.get('deleted') or payload.get('dead') or
                payload.get('type') != 'story' or str(payload.get('id')) != item_id):
            return FetchResult(ok=False, provider=self.name, url=url, error='invalid_hn_item', error_code='invalid_identity')

        if payload.get('url'):
            return FetchResult(
                ok=False,
                provider=self.name,
                url=url,
                title=payload.get('title') or '',
                error='external_hn_story',
                metadata={'external_url': payload.get('url')},
            )

        try:
            candidate = hn_candidate(payload, target_url=url, retrieved_from_url=api_url,
                                     request_started_at=started, source_item_id=item_id)
        except (InvalidIdentity, ValueError, TypeError):
            return FetchResult(False, self.name, url=url, error='invalid_identity', error_code='invalid_identity')
        return _candidate_result(candidate, self.name, expected_title=expected_title, summary=summary)


class LeiphoneFeedProvider:
    """Read Leiphone articles from the site's public RSS full-text entries."""

    name = 'leiphone_feed'
    feed_url = 'https://www.leiphone.com/feed'

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        if normalize_domain(url) != 'leiphone.com':
            return FetchResult(ok=False, provider=self.name, url=url, error='not_leiphone_article')

        try:
            root = ET.fromstring(self._download())
        except (BudgetDeferred, ExecutionStopped):
            raise
        except Exception as exc:
            return transport_failure(exc, provider=self.name, url=url)

        requested_key = _article_url_key(url)
        for item in root.iter():
            if _xml_local_name(item.tag) != 'item':
                continue

            fields = {
                _xml_local_name(child.tag): ''.join(child.itertext()).strip()
                for child in item
            }
            item_url = fields.get('link', '')
            if _article_url_key(item_url) != requested_key:
                continue

            title = fields.get('title', '') or expected_title or ''
            description_html = fields.get('description', '')
            if not description_html:
                return FetchResult(ok=False, provider=self.name, url=url, title=title, error='empty_feed_description')

            markdown = html_fragment_to_markdown(description_html, url)
            validation = validate_markdown(
                markdown,
                expected_title=expected_title,
                extracted_title=title,
                url=url,
                min_chars=_min_chars_for_url(url),
            )
            if not validation.ok:
                return FetchResult(
                    ok=False,
                    provider=self.name,
                    url=url,
                    title=title,
                    markdown=markdown,
                    quality_score=validation.score,
                    error='validation_failed:' + ','.join(validation.reasons),
                    validation_reasons=list(validation.reasons),
                    content_length=len(markdown),
                    extractor=self.name,
                )

            return FetchResult(
                ok=True,
                provider=self.name,
                url=url,
                title=title,
                markdown=markdown,
                quality_score=validation.score,
                content_length=len(markdown),
                extractor=self.name,
                metadata={'trusted_full_article_source': 'rss_description'},
            )

        return FetchResult(ok=False, provider=self.name, url=url, error='feed_item_not_found')

    def _download(self) -> bytes:
        # Leiphone's public RSS endpoint rejects browser-style user agents with
        # HTTP 403 while serving ordinary feed clients. Keep this override
        # scoped to the fixed feed URL; article URLs still use normal headers.
        req = urllib.request.Request(
            self.feed_url,
            headers={
                'User-Agent': LEIPHONE_FEED_USER_AGENT,
                'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.7',
            },
        )
        with _open_url(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
            return resp.read()


class JinaProvider:
    name = 'jina'

    def __init__(self, timeout: int = 15, retries: int = 1):
        self.timeout = timeout
        self.retries = 0  # Retry scheduling belongs to the persistent task, not each provider.

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        if settings.DJANGO_ENV == 'production':
            return FetchResult(ok=False, provider=self.name, url=url, error='unsafe_transport_disabled')
        return self._fetch_jina(url, expected_title=expected_title, summary=summary)

    def _fetch_jina(
        self,
        url: str,
        *,
        expected_title: str | None = None,
        summary: str | None = None,
    ) -> FetchResult:
        from api.services.article_fetch_monitor import observe_jina_candidate
        if not observe_jina_candidate(normalize_domain(url)):
            return FetchResult(ok=False, provider=self.name, url=url, error='jina_policy_disabled', error_code='unsupported')
        jina_url = f'https://r.jina.ai/{url}'
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                headers = {'Accept': 'text/plain', 'User-Agent': USER_AGENT}
                if os.environ.get('JINA_API_KEY'):
                    headers['Authorization'] = 'Bearer ' + os.environ['JINA_API_KEY']
                req = urllib.request.Request(jina_url, headers=headers)
                with _open_url(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                markdown_match = re.search(r'Markdown Content:\n([\s\S]+)$', text)
                markdown = markdown_match.group(1).strip() if markdown_match else text.strip()
                title = _parse_jina_title(text)
                if not markdown or markdown == 'Sorry.':
                    raise ValueError('jina returned empty content')
                markdown = clean_content(markdown, url)
                validation = validate_markdown(
                    markdown,
                    expected_title=expected_title,
                    extracted_title=title,
                    url=url,
                    summary=summary,
                    min_chars=_min_chars_for_url(url),
                )
                if not validation.ok:
                    return FetchResult(
                        ok=False,
                        provider=self.name,
                        url=url,
                        title=title,
                        markdown=markdown,
                        quality_score=validation.score,
                        error='validation_failed:' + ','.join(validation.reasons),
                    )
                return FetchResult(
                    ok=True,
                    provider=self.name,
                    url=url,
                    title=title,
                    markdown=markdown,
                    quality_score=validation.score,
                )
            except urllib.error.HTTPError as exc:
                return transport_failure(exc, provider=self.name, url=url)
            except (BudgetDeferred, ExecutionStopped):
                raise
            except Exception as exc:
                last_error = exc

        return transport_failure(last_error or RuntimeError('provider_error'), provider=self.name, url=url)


class VentureBeatJinaProvider(JinaProvider):
    """Jina fallback restricted to public HTTPS articles on VentureBeat."""

    name = 'venturebeat_jina'

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        try:
            parsed = urlparse(url)
            domain = normalize_domain(url)
            supported = (
                parsed.scheme.lower() == 'https'
                and domain == 'venturebeat.com'
                and parsed.username is None
                and parsed.password is None
                and parsed.port in {None, 443}
            )
        except (TypeError, ValueError):
            domain = ''
            supported = False
        if not supported:
            error = 'not_venturebeat_article' if domain != 'venturebeat.com' else 'unsupported_venturebeat_url'
            return FetchResult(ok=False, provider=self.name, url=url, error=error)
        # The article path is sufficient for this fallback. Do not disclose
        # tracking or other query values to the third-party reader service.
        from api.services.article_identity import normalize_article_url
        target_url = normalize_article_url(url)
        if urlparse(target_url).query:
            return FetchResult(ok=False, provider=self.name, url=url, error='reader_query_not_supported', error_code='not_applicable')
        return self._fetch_jina(target_url, expected_title=expected_title, summary=summary)


class TrustedNewsJinaProvider(JinaProvider):
    """Jina fallback restricted to explicitly reviewed public news domains."""

    name = 'trusted_news_jina'

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        try:
            parsed = urlparse(url)
            domain = normalize_domain(url)
            supported = (
                parsed.scheme.lower() == 'https'
                and bool(domain)
                and parsed.username is None
                and parsed.password is None
                and parsed.port in {None, 443}
            )
        except (TypeError, ValueError):
            domain = ''
            supported = False
        if not supported:
            return FetchResult(ok=False, provider=self.name, url=url, error='unsupported_trusted_news_url')
        from api.services.article_fetch_monitor import observe_jina_candidate
        if not observe_jina_candidate(domain):
            return FetchResult(ok=False, provider=self.name, url=url, error='jina_policy_disabled', error_code='unsupported')
        # Never disclose tracking/query values or fragments to the reader
        # service.  The explicitly enabled public article path is sufficient.
        from api.services.article_identity import normalize_article_url
        target_url = normalize_article_url(url)
        if urlparse(target_url).query:
            return FetchResult(ok=False, provider=self.name, url=url, error='reader_query_not_supported', error_code='not_applicable')
        return self._fetch_jina(target_url, expected_title=expected_title, summary=summary)


class ScrapyHTTPProvider:
    """Scrapy-compatible direct HTML fetcher.

    It mirrors the crawler headers and extraction rules, but deliberately runs as
    normal synchronous code for API requests to avoid Twisted reactor lifecycle
    issues inside Django. The extractor registry is shared with future Scrapy
    spider/worker implementations.
    """

    name = 'scrapy_http'

    def __init__(self, timeout: int = 20, retries: int = 1):
        self.timeout = timeout
        self.retries = 0  # Retry scheduling belongs to the persistent task, not each provider.

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                html = self._download(url)
                extracted = extract_markdown_from_html(html, url)
                markdown = clean_content(extracted.markdown, url)
                validation = validate_markdown(
                    markdown,
                    expected_title=expected_title,
                    extracted_title=extracted.title,
                    url=url,
                    canonical_url=extracted.canonical_url,
                    summary=summary,
                    min_chars=_min_chars_for_url(url),
                )
                if not validation.ok:
                    return FetchResult(
                        ok=False,
                        provider=self.name,
                        url=url,
                        title=extracted.title,
                        canonical_url=extracted.canonical_url,
                        markdown=markdown,
                        quality_score=validation.score,
                        error='validation_failed:' + ','.join(validation.reasons),
                    )
                return FetchResult(
                    ok=True,
                    provider=self.name,
                    url=url,
                    title=extracted.title,
                    canonical_url=extracted.canonical_url,
                    markdown=markdown,
                    quality_score=validation.score,
                )
            except (BudgetDeferred, ExecutionStopped):
                raise
            except Exception as exc:
                last_error = exc

        return transport_failure(last_error or RuntimeError('provider_error'), provider=self.name, url=url)

    def _download(self, url: str) -> str:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with _open_url(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read()
            content_type = resp.headers.get('content-type', '')
        encoding = _encoding_from_content_type(content_type) or 'utf-8'
        return raw.decode(encoding, errors='replace')


class ScrapySubprocessProvider:
    """Run the Scrapy-compatible article fetch command behind a process boundary."""

    name = 'scrapy_subprocess'

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        if settings.DJANGO_ENV == 'production':
            return FetchResult(ok=False, provider=self.name, url=url, error='unsafe_transport_disabled')
        cmd = [
            sys.executable,
            'manage.py',
            'fetch_article_url',
            url,
        ]
        if expected_title:
            cmd.extend(['--expected-title', expected_title])
        if summary:
            cmd.extend(['--summary', summary])
        try:
            completed = subprocess.run(
                cmd,
                cwd=_backend_dir(),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return FetchResult(ok=False, provider=self.name, url=url, error='scrapy subprocess timeout')
        except (BudgetDeferred, ExecutionStopped):
            raise
        except Exception as exc:
            return transport_failure(exc, provider=self.name, url=url)

        if completed.returncode != 0:
            return FetchResult(
                ok=False,
                provider=self.name,
                url=url,
                error=(completed.stderr or completed.stdout or f'exit {completed.returncode}').strip(),
            )
        try:
            data = json.loads(completed.stdout)
        except (BudgetDeferred, ExecutionStopped):
            raise
        except Exception as exc:
            return FetchResult(ok=False, provider=self.name, url=url, error=f'invalid json: {exc}')

        return FetchResult(
            ok=bool(data.get('ok')),
            provider=data.get('provider') or self.name,
            url=data.get('url') or url,
            title=data.get('title') or '',
            canonical_url=data.get('canonical_url') or '',
            markdown=data.get('markdown') or '',
            quality_score=float(data.get('quality_score') or 0.0),
            error=data.get('error') or '',
        )



def _github_repo_path(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(url)
        if normalize_domain(parsed.netloc) != 'github.com':
            return None
        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) < 2:
            return None
        owner, repo = parts[0], parts[1]
        if owner in {'topics', 'trending', 'marketplace', 'features', 'collections', 'orgs'}:
            return None
        if repo.endswith('.git'):
            repo = repo[:-4]
        return owner, repo
    except Exception:
        return None


def _github_readme_urls(owner: str, repo: str) -> list[str]:
    base = f'https://raw.githubusercontent.com/{owner}/{repo}'
    names = ['README.md', 'readme.md', 'README.markdown', 'README.mdown']
    branches = ['HEAD', 'main', 'master']
    return [f'{base}/{branch}/{name}' for branch in branches for name in names]


def _parse_jina_title(text: str) -> str:
    match = re.search(r'^Title:\s*(.+)$', text or '', flags=re.MULTILINE)
    return match.group(1).strip() if match else ''


def _hackernews_item_id(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = normalize_domain(parsed.netloc)
        if domain != 'news.ycombinator.com':
            return ''
        return (parse_qs(parsed.query).get('id') or [''])[0]
    except Exception:
        return ''


def _article_url_key(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url)
        return normalize_domain(parsed.netloc), parsed.path.rstrip('/')
    except Exception:
        return '', ''


def _xml_local_name(tag: str) -> str:
    return str(tag).rsplit('}', 1)[-1]


def _min_chars_for_url(url: str) -> int:
    rule = get_site_rule(url)
    return rule.min_length if rule else 300


def _encoding_from_content_type(content_type: str) -> str:
    match = re.search(r'charset=([^;]+)', content_type or '', flags=re.I)
    return match.group(1).strip() if match else ''


def _backend_dir() -> str:
    # providers.py = backend/api/services/article_fetcher/providers.py
    from pathlib import Path

    return str(Path(__file__).resolve().parents[3])


def default_providers(url=None) -> list:
    host = (urlparse(url).hostname or '').lower() if url else ''
    if host == 'dev.to':
        return [DevToAPIProvider()]
    if host == 'news.ycombinator.com':
        return [HackerNewsAPIProvider()]
    if host == 'github.com' and _github_repo_path(url):
        return [GitHubReadmeProvider()]
    providers = [
        HackerNewsAPIProvider(),
        GitHubReadmeProvider(),
        DevToAPIProvider(),
    ]
    providers.append(ScrapyHTTPProvider())
    providers.append(TrustedNewsJinaProvider(timeout=12, retries=0))
    return providers
