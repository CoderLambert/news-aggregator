from __future__ import annotations

import html as html_lib
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

from api.services.content_cleaner import clean_content

from .extractors import extract_markdown_from_html
from .site_rules import get_site_rule, normalize_domain
from .types import FetchResult
from .validators import validate_markdown

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
DEFAULT_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


class GitHubReadmeProvider:
    """Fetch repository README as raw Markdown for GitHub repo URLs.

    Extracting GitHub's rendered HTML can split highlighted code into many
    token lines. Raw README Markdown preserves fenced code blocks exactly.
    """

    name = 'github_readme'

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        repo = _github_repo_path(url)
        if not repo:
            return FetchResult(ok=False, provider=self.name, url=url, error='not_github_repo')

        owner, name = repo
        title = expected_title or f'{owner}/{name}'
        errors: list[str] = []

        for readme_url in _github_readme_urls(owner, name):
            try:
                markdown = self._download(readme_url)
            except urllib.error.HTTPError as exc:
                errors.append(f'HTTP {exc.code}: {readme_url}')
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue

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
            )

        return FetchResult(ok=False, provider=self.name, url=url, title=title, error='; '.join(errors) or 'readme_not_found')

    def _download(self, url: str) -> str:
        req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, 'Accept': 'text/plain,*/*;q=0.8'})
        with urllib.request.urlopen(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
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
        try:
            req = urllib.request.Request(api_url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='replace') or '{}')
        except Exception as exc:
            return FetchResult(ok=False, provider=self.name, url=url, error=str(exc))

        if not isinstance(payload, dict) or payload.get('deleted') or payload.get('dead'):
            return FetchResult(ok=False, provider=self.name, url=url, error='invalid_hn_item')

        if payload.get('url'):
            return FetchResult(
                ok=False,
                provider=self.name,
                url=url,
                title=payload.get('title') or '',
                error='external_hn_story',
                metadata={'external_url': payload.get('url')},
            )

        title = payload.get('title') or expected_title or ''
        text_html = payload.get('text') or ''
        if not text_html.strip():
            return FetchResult(ok=False, provider=self.name, url=url, title=title, error='empty_hn_self_post')

        extracted = extract_markdown_from_html(
            f'<html><body><article><h1>{html_lib.escape(title)}</h1><div class="toptext">{text_html}</div></article></body></html>',
            url,
        )
        markdown = clean_content(extracted.markdown, url)
        min_chars = _min_chars_for_url(url)
        validation = validate_markdown(
            markdown,
            expected_title=expected_title,
            extracted_title=extracted.title or title,
            url=url,
            summary=summary,
            min_chars=min_chars,
        )
        if not validation.ok:
            return FetchResult(
                ok=False,
                provider=self.name,
                url=url,
                title=extracted.title or title,
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
            title=extracted.title or title,
            markdown=markdown,
            quality_score=validation.score,
            content_length=len(markdown),
            extractor=self.name,
        )


class JinaProvider:
    name = 'jina'

    def __init__(self, timeout: int = 15, retries: int = 1):
        self.timeout = timeout
        self.retries = retries

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        jina_url = f'https://r.jina.ai/{url}'
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    jina_url,
                    headers={'Accept': 'text/plain', 'User-Agent': USER_AGENT},
                )
                with urllib.request.urlopen(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
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
                return FetchResult(ok=False, provider=self.name, url=url, error=f'HTTP {exc.code}: {exc.reason}')
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        return FetchResult(ok=False, provider=self.name, url=url, error=str(last_error or 'unknown error'))


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
        self.retries = retries

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
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        return FetchResult(ok=False, provider=self.name, url=url, error=str(last_error or 'unknown error'))

    def _download(self, url: str) -> str:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=self.timeout, context=ssl.create_default_context()) as resp:
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
        except Exception as exc:
            return FetchResult(ok=False, provider=self.name, url=url, error=str(exc))

        if completed.returncode != 0:
            return FetchResult(
                ok=False,
                provider=self.name,
                url=url,
                error=(completed.stderr or completed.stdout or f'exit {completed.returncode}').strip(),
            )
        try:
            data = json.loads(completed.stdout)
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


def default_providers() -> list:
    return [HackerNewsAPIProvider(), GitHubReadmeProvider(), JinaProvider(), ScrapySubprocessProvider(), ScrapyHTTPProvider()]
