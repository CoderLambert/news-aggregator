"""Pure conversion of already obtained HTML; no fetching, extraction, or DB writes."""

from dataclasses import dataclass
from hashlib import sha256
from ipaddress import ip_address
import re
from urllib.parse import quote, urljoin, urlsplit

import nh3
from markdownify import MarkdownConverter


MAX_CONTENT_BYTES = 2 * 1024 * 1024
# Bump whenever cleaning, URL policy, Markdown formatting, or dependencies change.
CONVERSION_VERSION = "rss-html-v1:nh3-0.3.7:markdownify-1.2.3:bs4-4.15.0"


class ConversionError(ValueError):
    """A permanent conversion rejection, safe to persist without source HTML."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ConvertedContent:
    markdown: str
    raw_hash: str
    canonical_hash: str
    conversion_version: str = CONVERSION_VERSION


def _public_web_url(value: str, base_url: str, *, image: bool = False) -> str | None:
    # urlsplit silently drops some controls; reject them before parsing.
    if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        return None
    try:
        url = urljoin(base_url, value)
        parsed = urlsplit(url)
        if parsed.scheme not in ({"https"} if image else {"http", "https"}):
            return None
        if parsed.username is not None or parsed.password is not None or not parsed.hostname:
            return None
        host = parsed.hostname.rstrip(".").lower()
        # Accessing port also validates malformed/out-of-range ports.
        parsed.port
        try:
            address = ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
                return None
            if host.rsplit(".", 1)[-1].isdigit():
                return None  # browser-specific integer/short/octal IP spellings
            if host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".arpa")):
                return None
        else:
            if not address.is_global:
                return None
        # Markdown destinations must not allow parentheses/angle/whitespace injection.
        return quote(url, safe="/:?#[]@!$&*+,;=%~-._")
    except (ValueError, UnicodeError):
        return None


def _literal_markdown(text: str) -> str:
    text = text.replace("\\", "\\\\")
    for char in "`*_{}[]()#+-.!|>":
        text = text.replace(char, "\\" + char)
    return text.replace("<", "&lt;").replace("\r", " ").replace("\n", " ")


class _ContentConverter(MarkdownConverter):
    def process_tag(self, node, parent_tags=None):
        if node.name == "pre":
            # markdownify's ordinary text traversal strips edge spaces; HTML
            # <pre> text must instead survive exactly (with LF line endings).
            text = node.get_text()
            if not text:
                return ""
            fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", text)), default=0))
            return "\n\n" + fence + "\n" + text + "\n" + fence + "\n\n"
        return super().process_tag(node, parent_tags=parent_tags)

    def convert_code(self, el, text, parent_tags):
        if "_noformat" in parent_tags:
            return text
        text = el.get_text()
        if not text:
            return ""
        delimiter = "`" * (1 + max((len(x) for x in re.findall(r"`+", text)), default=0))
        padding = " " if text.startswith(("`", " ")) or text.endswith(("`", " ")) else ""
        return delimiter + padding + text + padding + delimiter

    def convert_a(self, el, text, parent_tags):
        href = el.get("href")
        if not href or "_noformat" in parent_tags or not text.strip():
            return text
        return "[" + text + "](" + href + ")"

    def convert_img(self, el, text, parent_tags):
        alt = _literal_markdown(el.get("alt", ""))
        src = el.get("src")
        return "![" + alt + "](" + src + ")" if src else alt


def convert_html(
    html: str,
    *,
    base_url: str,
    max_html_bytes: int = MAX_CONTENT_BYTES,
    max_markdown_bytes: int = MAX_CONTENT_BYTES,
) -> ConvertedContent:
    """Clean and convert one HTML fragment; limits count UTF-8 bytes, never truncate.

    ``raw_hash`` hashes the exact input HTML. It may only skip conversion when
    the conversion version AND article URL are unchanged. Completeness, ACL,
    candidate construction and historical-body updates belong to the caller.
    Empty output is returned for caller rejection, never declared complete.
    URL checks are lexical and make no DNS/network requests; renderer/deployment
    media restrictions must also cover public hostnames resolving privately.
    """
    if not isinstance(html, str):
        raise ConversionError("invalid_html")
    if max_html_bytes < 1 or max_markdown_bytes < 1:
        raise ValueError("content limits must be positive")
    try:
        raw = html.encode("utf-8")
    except UnicodeError:
        raise ConversionError("invalid_html") from None
    if len(raw) > max_html_bytes:
        raise ConversionError("html_too_large")
    if not isinstance(base_url, str) or _public_web_url(base_url, "") is None:
        raise ConversionError("invalid_base_url")

    def attribute_filter(tag: str, attribute: str, value: str) -> str | None:
        if attribute in {"href", "src"}:
            return _public_web_url(value, base_url, image=(tag == "img"))
        return value

    cleaned = nh3.clean(
        html.replace("\r\n", "\n").replace("\r", "\n"),
        tags={"p", "div", "span", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
              "strong", "b", "em", "i", "s", "del", "ul", "ol", "li", "blockquote",
              "pre", "code", "kbd", "samp", "a", "img", "table", "thead", "tbody",
              "tfoot", "tr", "th", "td", "caption", "dl", "dt", "dd"},
        clean_content_tags={"script", "style", "iframe", "object", "embed", "svg", "math",
                            "template", "noscript"},
        attributes={"a": {"href"}, "img": {"src", "alt"}},
        attribute_filter=attribute_filter,
        url_schemes={"http", "https"},
        url_relative=lambda value: _public_web_url(value, base_url),
        strip_comments=True,
    )
    markdown = _ContentConverter(
        # escape_misc also escapes entity-decoded HTML and Markdown-looking text.
        heading_style="ATX", bullets="-", escape_misc=True,
        autolinks=False, wrap=False, bs4_options="html.parser",
    ).convert(cleaned).strip("\n")
    if len(markdown.encode("utf-8")) > max_markdown_bytes:
        raise ConversionError("markdown_too_large")
    return ConvertedContent(
        markdown=markdown,
        raw_hash=sha256(raw).hexdigest(),
        canonical_hash=sha256(markdown.encode("utf-8")).hexdigest(),
    )
