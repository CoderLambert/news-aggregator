"""T06 pure conversion contract: no Django setup or database needed."""

from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from api.rss.content import CONVERSION_VERSION, ConversionError, convert_html


BASE = "https://publisher.example/posts/entry"


def convert(html, **kwargs):
    return convert_html(html, base_url=BASE, **kwargs)


def test_script_event_style_and_embedded_documents_are_removed():
    body = convert('''<p onclick="evil()" style="background:url(http://127.0.0.1)">safe</p>
        <script>script_secret()</script><style>style_secret</style>
        <iframe src="https://evil.example">frame_secret</iframe>
        <svg><a href="https://evil.example">svg_secret</a></svg>
        <object>object_secret</object><!-- comment_secret -->''').markdown
    assert body == "safe"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "jAvAsCrIpT:alert(1)", "java&#x09;script:alert(1)",
    "data:image/svg+xml,evil", "vbscript:evil", "file:///etc/passwd",
    "http://127.0.0.1/a", "https://[::1]/a", "https://10.0.0.1/a",
    "https://169.254.169.254/latest", "https://192.168.1.1/a",
    "https://2130706433/a", "https://0177.0.0.1/a", "https://0x7f000001/a",
    "https://miniflux/a", "https://engine.internal/a", "https://foo.local/a",
    "https://localhost./a", "https://x.localhost/a", "https://[::ffff:127.0.0.1]/a",
    "https://user:password@publisher.example/a", "https://publisher.example:99999/a",
])
def test_dangerous_schemes_and_internal_addresses_cannot_reach_markdown(url):
    assert convert(f'<a href="{url}">link</a><img src="{url}" alt="image">').markdown == "linkimage"


def test_relative_urls_use_publisher_base_and_images_require_https():
    body = convert('''<a href="../about?x=1&amp;y=2">About</a>
        <img src="//cdn.example/image.png" alt="photo">
        <img src="http://cdn.example/insecure.png" alt="insecure">
        <img src="/photo.png" alt="relative">''').markdown
    assert "[About](https://publisher.example/about?x=1&y=2)" in body
    assert "![photo](https://cdn.example/image.png)" in body
    assert "![relative](https://publisher.example/photo.png)" in body
    assert "insecure.png" not in body


def test_markdown_injection_in_alt_text_destinations_and_encoded_html_is_literal():
    body = convert('''<p>&lt;script&gt;alert(1)&lt;/script&gt; ![x](javascript:alert(2))</p>
        <img src="https://cdn.example/a)![pwn](javascript:bad)" alt="](&lt;script&gt;)![pwn]">
        <a href="https://publisher.example/a)![pwn](javascript:bad)">safe</a>''').markdown
    assert "<script>" not in body
    assert "![x]" not in body
    assert "%29!" in body and "%28javascript:bad%29" in body
    assert "![pwn](javascript:" not in body
    assert r"\]\(" in body


def test_titles_tables_lists_quotes_and_inline_formatting():
    body = convert('''<h1>Title</h1><h2>Details</h2><p><strong>Bold</strong> <em>em</em></p>
        <ul><li>First</li><li>Second<ul><li>Nested</li></ul></li></ul>
        <ol><li>One</li><li>Two</li></ol><blockquote><p>Quoted</p></blockquote>
        <table><thead><tr><th>Name</th><th>Value</th></tr></thead>
        <tbody><tr><td>a|b</td><td>2</td></tr></tbody></table>''').markdown
    for part in ["# Title", "## Details", "**Bold** *em*", "- First", "- Second", "Nested",
                 "1. One", "2. Two", "> Quoted", "| Name | Value |", "| a\\|b | 2 |"]:
        assert part in body


def test_preformatted_code_preserves_spaces_tabs_lines_entities_and_fence_text():
    code = "  a = `x`  \n\t```\n\n&lt;script&gt; &amp; value\n  "
    body = convert("<pre><code>" + code.replace("\n", "\r\n") + "</code></pre>").markdown
    assert body == "````\n  a = `x`  \n\t```\n\n<script> & value\n  \n````"
    assert "\r" not in body
    assert convert("<p><code> a`b </code></p>").markdown == "``  a`b  ``"


def test_raw_and_canonical_hashes_are_deterministic_and_versioned():
    html = "<p>你好\r\nworld</p>"
    first, second = convert(html), convert(html)
    assert first == second
    assert first.raw_hash == sha256(html.encode()).hexdigest()
    assert first.canonical_hash == sha256(first.markdown.encode()).hexdigest()
    assert first.conversion_version == CONVERSION_VERSION
    assert convert(html.replace("\r\n", "\n")).canonical_hash == first.canonical_hash
    assert convert(html.replace("\r\n", "\n")).raw_hash != first.raw_hash
    assert html == "<p>你好\r\nworld</p>"
    with pytest.raises(FrozenInstanceError):
        first.markdown = "mutated"


def test_limits_use_utf8_bytes_and_reject_instead_of_truncating():
    assert convert("你", max_html_bytes=3).markdown == "你"
    for kwargs, reason in [({"max_html_bytes": 2}, "html_too_large"),
                           ({"max_markdown_bytes": 2}, "markdown_too_large")]:
        with pytest.raises(ConversionError) as error:
            convert("你", **kwargs)
        assert error.value.code == reason
    with pytest.raises(ConversionError, match="html_too_large"):
        convert("a" * (2 * 1024 * 1024 + 1))
    # Markdown escaping can expand content beyond the output limit.
    with pytest.raises(ConversionError, match="markdown_too_large"):
        convert("[" * 20, max_html_bytes=20, max_markdown_bytes=20)


def test_empty_content_and_malformed_html_are_not_marked_complete():
    assert convert("<script>evil</script>").markdown == ""
    assert convert("<p>unclosed <b>bold").markdown == "unclosed **bold**"
    with pytest.raises(ConversionError, match="invalid_html"):
        convert("\ud800")
    with pytest.raises(ConversionError, match="invalid_base_url"):
        convert_html("safe", base_url="http://127.0.0.1/feed")
