import json

from django.core.management.base import BaseCommand

from api.services.article_fetcher.extractors import extract_markdown_from_html
from api.services.article_fetcher.providers import DEFAULT_HEADERS
from api.services.article_fetcher.site_rules import get_site_rule
from api.services.article_fetcher.types import FetchResult
from api.services.article_fetcher.validators import validate_markdown
from api.services.content_cleaner import clean_content


class Command(BaseCommand):
    help = 'Fetch a single article URL via the crawler-style HTML fetcher and emit JSON.'

    def add_arguments(self, parser):
        parser.add_argument('url')
        parser.add_argument('--expected-title', default='')
        parser.add_argument('--summary', default='')
        parser.add_argument('--timeout', type=int, default=45)

    def handle(self, *args, **options):
        url = options['url']
        expected_title = options['expected_title']
        summary = options['summary']
        timeout = options['timeout']

        try:
            html = _download(url, timeout=timeout)
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
                self._emit(FetchResult(
                    ok=False,
                    provider='scrapy_cli',
                    url=url,
                    title=extracted.title,
                    canonical_url=extracted.canonical_url,
                    markdown=markdown,
                    quality_score=validation.score,
                    error='validation_failed:' + ','.join(validation.reasons),
                ))
                return
            self._emit(FetchResult(
                ok=True,
                provider='scrapy_cli',
                url=url,
                title=extracted.title,
                canonical_url=extracted.canonical_url,
                markdown=markdown,
                quality_score=validation.score,
            ))
        except Exception as exc:
            self._emit(FetchResult(ok=False, provider='scrapy_cli', url=url, error=str(exc)))

    def _emit(self, result: FetchResult):
        self.stdout.write(json.dumps({
            'ok': result.ok,
            'provider': result.provider,
            'url': result.url,
            'title': result.title,
            'canonical_url': result.canonical_url,
            'markdown': result.markdown,
            'quality_score': result.quality_score,
            'error': result.error,
        }, ensure_ascii=False))


def _download(url: str, timeout: int = 45) -> str:
    import ssl
    import urllib.request

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
        raw = resp.read()
        content_type = resp.headers.get('content-type', '')
    encoding = _encoding_from_content_type(content_type) or 'utf-8'
    return raw.decode(encoding, errors='replace')


def _min_chars_for_url(url: str) -> int:
    rule = get_site_rule(url)
    return rule.min_length if rule else 300


def _encoding_from_content_type(content_type: str) -> str:
    import re

    match = re.search(r'charset=([^;]+)', content_type or '', flags=re.I)
    return match.group(1).strip() if match else ''
