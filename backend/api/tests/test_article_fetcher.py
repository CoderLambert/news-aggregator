from unittest.mock import patch

import json
from pathlib import Path

from django.core.management import call_command

from api.services.article_fetcher import FetchError, FetchResult, fetch_article_markdown
from api.services.article_fetcher.extractors import extract_markdown_from_html
from api.services.article_fetcher.providers import (
    GitHubReadmeProvider,
    HackerNewsAPIProvider,
    LeiphoneFeedProvider,
    ScrapyHTTPProvider,
    ScrapySubprocessProvider,
    default_providers,
)
from api.services.article_fetcher.site_rules import get_site_rule, normalize_domain
from api.services.article_fetcher.validators import _same_domain, validate_markdown


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


def test_extract_markdown_preserves_headings_paragraphs_lists_and_line_breaks():
    html = '''
    <article>
      <h2>制度边界</h2>
      <p>第一行<br>段内换行</p>
      <p>第二段正文。</p>
      <ul><li>第一项</li><li>第二项</li></ul>
    </article>
    '''

    result = extract_markdown_from_html(html, 'https://example.com/article')

    assert '## 制度边界' in result.markdown
    assert '第一行\\\n段内换行' in result.markdown
    assert '第二段正文。' in result.markdown
    assert '- 第一项\n- 第二项' in result.markdown
    assert result.markdown.index('## 制度边界') < result.markdown.index('第一行')
    assert result.markdown.index('第一行') < result.markdown.index('第二段正文。')
    assert result.markdown.index('第二段正文。') < result.markdown.index('- 第一项')


def test_deepmind_extractor_removes_share_menu_and_related_story_carousel():
    html = '''
    <html><body><main>
      <article>
        <h1>Introducing a live model</h1>
        <!-- Share Dropdown Menu -->
        <div class="uni-share-dropdown"><ul><li>Share on X</li></ul></div>
        <p>The first article paragraph links to<a href="/models/live">Gemini Live</a>.</p>
        <p>The second article paragraph preserves the rest of the source body.</p>
      </article>
      <div class="uni-blog-article-tags"><span>Posted in:</span></div>
      <uni-related-articles><h2>Related stories</h2><p>Unrelated card copy.</p></uni-related-articles>
    </main></body></html>
    '''

    result = extract_markdown_from_html(
        html,
        'https://deepmind.google/blog/introducing-a-live-model/',
    )

    assert 'links to [Gemini Live](https://deepmind.google/models/live)' in result.markdown
    assert 'second article paragraph' in result.markdown
    assert 'Share on X' not in result.markdown
    assert 'Share Dropdown Menu' not in result.markdown
    assert 'Related stories' not in result.markdown
    assert 'Unrelated card copy' not in result.markdown
    assert 'Posted in:' not in result.markdown


def test_extract_markdown_keeps_block_boundaries_and_html_br_hard_breaks():
    fixture_path = Path(__file__).parent / 'full_article_renderer_contract.json'
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))

    result = extract_markdown_from_html(fixture['html'], 'https://example.com/article')

    assert result.markdown == fixture['markdown']


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
    assert isinstance(providers[2], LeiphoneFeedProvider)


def test_leiphone_feed_provider_preserves_real_article_structure():
    body = '这一段补充真实文章背景、评测方法、成本数据与使用限制。' * 20
    feed = f'''<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title><![CDATA[Claude Haiku 5.5 降本背后]]></title>
      <link>https://www.leiphone.com/category/ai/example.html</link>
      <description><![CDATA[
        <section><p>第一段真实正文，包含足够的背景信息与产品数据。</p></section>
        <section><h2>01 复杂编程仍有差距</h2><p>第二段真实正文。{body}</p>
        <ul><li>操作能力提升</li><li>复杂编程仍需更大模型</li></ul>
        <img src="https://static.leiphone.com/article.png" alt="评测图" /></section>
      ]]></description>
    </item></channel></rss>'''.encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return feed

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()):
        result = LeiphoneFeedProvider(timeout=8).fetch(
            'https://www.leiphone.com/category/ai/example.html',
            expected_title='Claude Haiku 5.5 降本背后',
        )

    assert result.ok is True
    assert result.provider == 'leiphone_feed'
    assert '第一段真实正文' in result.markdown
    assert '## 01 复杂编程仍有差距' in result.markdown
    assert '- 操作能力提升\n- 复杂编程仍需更大模型' in result.markdown
    assert '![评测图](https://static.leiphone.com/article.png)' in result.markdown
    assert result.metadata == {'trusted_full_article_source': 'rss_description'}


def test_leiphone_feed_full_article_is_not_rejected_as_its_legacy_summary():
    provider = LeiphoneFeedProvider()
    markdown = '## 正文\n\n' + ('真实正文段落，来自站点公开 RSS。' * 80)
    result = FetchResult(
        ok=True,
        provider=provider.name,
        url='https://www.leiphone.com/category/ai/example.html',
        title='真实文章',
        markdown=markdown,
        metadata={'trusted_full_article_source': 'rss_description'},
    )

    with patch.object(provider, 'fetch', return_value=result):
        fetched = fetch_article_markdown(
            result.url,
            expected_title='真实文章',
            summary=markdown.replace('## 正文\n\n', ''),
            providers=[provider],
        )

    assert fetched.ok is True
    assert fetched.provider == 'leiphone_feed'


def test_untrusted_provider_cannot_skip_summary_similarity_validation():
    markdown = '这只是摘要内容，不能冒充抓取到的全文。' + ''.join(
        f'第{index}项摘要信息。' for index in range(80)
    )

    class Provider:
        name = 'untrusted'

        def fetch(self, url, expected_title=None, summary=None):
            return FetchResult(
                ok=True,
                provider=self.name,
                url=url,
                title=expected_title or '',
                markdown=markdown,
                metadata={'trusted_full_article_source': 'rss_description'},
            )

    try:
        fetch_article_markdown(
            'https://example.com/article',
            expected_title='真实文章',
            summary=markdown,
            providers=[Provider()],
        )
    except FetchError as exc:
        assert 'summary_sized' in exc.failures[0].validation_reasons
    else:
        raise AssertionError('expected FetchError')


def test_leiphone_feed_provider_does_not_accept_another_article():
    feed = b'''<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title>Another article</title>
      <link>https://www.leiphone.com/category/ai/another.html</link>
      <description><![CDATA[<p>Another article body.</p>]]></description>
    </item></channel></rss>'''

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return feed

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()):
        result = LeiphoneFeedProvider().fetch(
            'https://www.leiphone.com/category/ai/requested.html',
            expected_title='Requested article',
        )

    assert result.ok is False
    assert result.error == 'feed_item_not_found'


def test_leiphone_feed_provider_rejects_invalid_xml():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'<rss><channel>'

    with patch('api.services.article_fetcher.providers.urllib.request.urlopen', return_value=Response()):
        result = LeiphoneFeedProvider().fetch(
            'https://www.leiphone.com/category/ai/requested.html',
            expected_title='Requested article',
        )

    assert result.ok is False
    assert result.error


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


def test_deepmind_official_blog_redirect_is_an_explicit_canonical_alias():
    markdown = 'Gemini Live Avatar article paragraph. ' * 30

    result = validate_markdown(
        markdown=markdown,
        expected_title='Introducing Gemini 3.8 Live with Live Avatar',
        extracted_title='Introducing Gemini 3.8 Live with Live Avatar',
        url='https://deepmind.google/blog/introducing-gemini-38-live-with-live-avatar/',
        canonical_url='https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-8-live-with-live-avatar/',
    )

    assert result.ok


def test_unlisted_cross_domain_canonical_is_still_rejected():
    markdown = '权责边界文章正文段落。' * 100

    result = validate_markdown(
        markdown=markdown,
        expected_title='迁移权责确权层',
        extracted_title='迁移权责确权层',
        url='https://leiphone.com/category/industrynews/article.html',
        canonical_url='https://untrusted.example/article.html',
    )

    assert not result.ok
    assert 'canonical_domain_mismatch' in result.reasons



def test_normalize_domain_uses_parsed_hostname_and_rejects_malformed_urls():
    assert normalize_domain(
        'https://reader:secret@WWW.DeepMind.Google.:8443/article'
    ) == 'deepmind.google'
    assert normalize_domain('deepmind.google/article') == 'deepmind.google'
    assert normalize_domain('https://[malformed') == ''


def test_site_rule_matching_uses_the_real_hostname():
    assert get_site_rule(
        'https://reader:secret@www.deepmind.google.:8443/article'
    ).name == 'Google DeepMind'
    assert get_site_rule('https://deepmind.google@evil.example/article') is None
    assert get_site_rule('https://deepmind.google.evil.example/article') is None


def test_explicit_canonical_alias_is_hostname_exact_and_fails_closed():
    source = 'https://deepmind.google/blog/story'

    assert _same_domain(source, 'https://user:secret@www.deepmind.google.:443/story')
    assert _same_domain(source, 'https://www.blog.google.:443/story')
    assert not _same_domain(source, 'https://extra.blog.google/story')
    assert not _same_domain(source, 'https://reader@evil.example/story')
    assert not _same_domain(source, 'https://[malformed')
    assert not _same_domain('https://[malformed', 'https://blog.google/story')
