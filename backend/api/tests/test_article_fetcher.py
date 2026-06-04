from unittest.mock import patch

import json

from django.core.management import call_command

from api.services.article_fetcher import FetchError, FetchResult, fetch_article_markdown
from api.services.article_fetcher.extractors import extract_markdown_from_html
from api.services.article_fetcher.providers import (
    GitHubReadmeProvider,
    HackerNewsAPIProvider,
    ScrapyHTTPProvider,
    ScrapySubprocessProvider,
    default_providers,
)
from api.services.article_fetcher.validators import validate_markdown


class _FailingProvider:
    name = 'failing'

    def fetch(self, url, expected_title=None):
        return FetchResult(ok=False, provider=self.name, error='reset')




class _ShortProductHuntProvider:
    name = 'short-producthunt'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or '',
            markdown='LaunchPad\n\nLaunchPad helps teams publish customer-ready product updates and roadmap notes. It organizes launch feedback, changelogs, roadmap ideas, and community updates in one concise workspace.',
        )


class _WorkingProvider:
    name = 'working'

    def fetch(self, url, expected_title=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or 'Example Article',
            markdown='Example Article\n\n' + ('Real paragraph with enough article words. ' * 30),
            quality_score=0.9,
        )


class _HackerNewsExternalStoryProvider:
    name = 'hackernews_api'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=False,
            provider=self.name,
            url=url,
            title=expected_title or '',
            error='external_hn_story',
            metadata={'external_url': 'https://example.com/original-article'},
        )


class _RecordingWorkingProvider:
    name = 'recording-working'

    def __init__(self):
        self.seen_urls = []

    def fetch(self, url, expected_title=None, summary=None):
        self.seen_urls.append(url)
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or 'External Article',
            markdown='External Article\n\n' + ('Real original external article paragraph. ' * 30),
            quality_score=0.9,
        )


def test_fetch_article_markdown_redirects_hn_external_story_to_original_url():
    recorder = _RecordingWorkingProvider()

    result = fetch_article_markdown(
        'https://news.ycombinator.com/item?id=456',
        expected_title='External Article',
        providers=[_HackerNewsExternalStoryProvider(), recorder],
    )

    assert result.ok is True
    assert result.url == 'https://example.com/original-article'
    assert recorder.seen_urls == ['https://example.com/original-article']


def test_fetch_article_markdown_uses_site_rule_min_length_on_final_validation():
    result = fetch_article_markdown(
        'https://www.producthunt.com/products/launchpad',
        expected_title='LaunchPad',
        providers=[_ShortProductHuntProvider()],
    )

    assert result.ok is True
    assert result.content_length == len(result.markdown)


def test_fetch_article_markdown_tries_next_provider_after_failure():
    result = fetch_article_markdown(
        'https://example.com/article',
        expected_title='Example Article',
        providers=[_FailingProvider(), _WorkingProvider()],
    )

    assert result.ok is True
    assert result.provider == 'working'
    assert 'Real paragraph' in result.markdown


def test_fetch_article_markdown_raises_when_all_real_providers_fail():
    try:
        fetch_article_markdown(
            'https://example.com/article',
            expected_title='Example Article',
            providers=[_FailingProvider()],
        )
    except FetchError as exc:
        assert '全部真实原文抓取方式失败' in str(exc)
        assert exc.failures[0].provider == 'failing'
    else:
        raise AssertionError('expected FetchError')


def test_extract_markdown_from_html_prefers_article_body_and_strips_chrome():
    html = '''
    <html><head><title>Example Article - Site</title><link rel="canonical" href="https://example.com/article" /></head>
    <body>
      <nav>Home Subscribe Login</nav>
      <article>
        <h1>Example Article</h1>
        <p>This is the first real paragraph with important details.</p>
        <p>This is the second real paragraph with more factual content and context.</p>
        <script>alert('x')</script>
      </article>
      <footer>Related articles and footer links</footer>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://example.com/article')

    assert result.title == 'Example Article'
    assert result.canonical_url == 'https://example.com/article'
    assert '# Example Article' in result.markdown
    assert 'first real paragraph' in result.markdown
    assert 'Home Subscribe Login' not in result.markdown
    assert 'Related articles' not in result.markdown


def test_validate_markdown_rejects_summary_sized_content():
    result = validate_markdown(
        markdown='Short summary only.',
        expected_title='Example Article',
        summary='Short summary only.',
    )

    assert result.ok is False
    assert 'too_short' in result.reasons


def test_scrapy_subprocess_provider_parses_json_success():
    class Completed:
        returncode = 0
        stdout = '{"ok": true, "provider": "scrapy_cli", "url": "https://example.com/a", "title": "Example Article", "markdown": "Example Article\\n\\nReal paragraph. Real paragraph. Real paragraph.", "quality_score": 0.8}'
        stderr = ''

    with patch('api.services.article_fetcher.providers.subprocess.run', return_value=Completed()) as run:
        result = ScrapySubprocessProvider(timeout=12).fetch('https://example.com/a', expected_title='Example Article')

    assert result.ok is True
    assert result.provider == 'scrapy_cli'
    assert 'Real paragraph' in result.markdown
    assert run.call_args.kwargs['timeout'] == 12




def test_default_providers_prioritizes_hackernews_api_before_generic_jina():
    providers = default_providers()

    assert isinstance(providers[0], HackerNewsAPIProvider)
    assert isinstance(providers[1], GitHubReadmeProvider)


def test_hackernews_api_provider_extracts_self_post_text_without_comments():
    payload = {
        'id': 123,
        'type': 'story',
        'title': 'Ask HN: Practical testing?',
        'text': '<p>I am looking for practical testing workflows that keep production code honest.</p><p>What patterns helped your team avoid regressions while moving quickly?</p>',
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            import json
            return json.dumps(payload).encode('utf-8')

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()) as urlopen:
        result = HackerNewsAPIProvider(timeout=8).fetch(
            'https://news.ycombinator.com/item?id=123',
            expected_title='Ask HN: Practical testing?',
        )

    assert result.ok is True
    assert result.provider == 'hackernews_api'
    assert result.title == 'Ask HN: Practical testing?'
    assert 'practical testing workflows' in result.markdown
    assert 'avoid regressions' in result.markdown
    assert 'comment' not in result.markdown.lower()
    assert urlopen.call_args.kwargs['timeout'] == 8


def test_hackernews_api_provider_skips_external_link_story():
    payload = {
        'id': 456,
        'type': 'story',
        'title': 'External article',
        'url': 'https://example.com/original-article',
        'text': '',
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            import json
            return json.dumps(payload).encode('utf-8')

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()):
        result = HackerNewsAPIProvider().fetch('https://news.ycombinator.com/item?id=456')

    assert result.ok is False
    assert result.provider == 'hackernews_api'
    assert result.error == 'external_hn_story'
    assert result.metadata['external_url'] == 'https://example.com/original-article'


def test_github_readme_provider_fetches_raw_markdown_and_preserves_code_lines():
    markdown = '''# CloakHQ/CloakBrowser

Stealth Chromium article body with enough words to satisfy validation. This README preserves source code formatting and avoids GitHub rendered HTML token splitting.

```python
from cloakbrowser import launch
browser = launch()
page = browser.new_page()
```
'''

    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class Response:
        headers = Headers({'content-type': 'text/plain; charset=utf-8'})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return markdown.encode('utf-8')

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()) as urlopen:
        result = GitHubReadmeProvider(timeout=8).fetch(
            'https://github.com/CloakHQ/CloakBrowser',
            expected_title='CloakHQ/CloakBrowser',
        )

    assert result.ok is True
    assert result.provider == 'github_readme'
    assert 'from cloakbrowser import launch' in result.markdown
    assert 'from\ncloakbrowser\nimport\nlaunch' not in result.markdown
    assert 'raw.githubusercontent.com/CloakHQ/CloakBrowser/HEAD/README.md' in urlopen.call_args.args[0].full_url


def test_fetch_article_url_command_uses_site_rule_min_length_for_short_pages(capsys):
    html = '''
    <html><body>
      <main><section class="styles_productHero__abc">
        <h1>LaunchPad</h1>
        <p>LaunchPad helps teams publish product updates with customer-ready release notes.</p>
        <p>It organizes feedback, roadmap ideas, changelogs, and community launch materials.</p>
      </section></main>
    </body></html>
    '''

    with patch('api.management.commands.fetch_article_url._download', return_value=html):
        call_command(
            'fetch_article_url',
            'https://www.producthunt.com/products/launchpad',
            expected_title='LaunchPad',
        )

    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is True
    assert payload['provider'] == 'scrapy_cli'
    assert len(payload['markdown']) < 300


def test_scrapy_http_provider_uses_site_rule_min_length_for_short_valid_pages():
    html = '''
    <html><body>
      <main>
        <section class="styles_productHero__abc">
          <h1>LaunchPad</h1>
          <p>LaunchPad helps teams publish product updates with customer-ready release notes.</p>
          <p>It organizes feedback, roadmap ideas, changelogs, and community launch materials.</p>
        </section>
      </main>
    </body></html>
    '''

    provider = ScrapyHTTPProvider(timeout=5, retries=0)
    with patch.object(provider, '_download', return_value=html):
        result = provider.fetch('https://www.producthunt.com/products/launchpad', expected_title='LaunchPad')

    assert result.ok is True
    assert result.provider == 'scrapy_http'
    assert len(result.markdown) < 300
    assert result.quality_score >= 0.8
