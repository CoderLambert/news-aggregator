from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class SiteRule:
    domains: tuple[str, ...]
    selectors: tuple[str, ...]
    remove_selectors: tuple[str, ...] = field(default_factory=tuple)
    min_length: int = 600
    title_selectors: tuple[str, ...] = ('h1', '[data-testid="headline"]')
    name: str = ''


# Domains protected by WAF/CAPTCHA that cannot be fetched via automated means.
# Skip these entirely in fetch-full to avoid hanging on timeouts.
WAF_BLOCKED_DOMAINS: tuple[str, ...] = (
    'infoq.com',
)


SITE_RULES: tuple[SiteRule, ...] = (
    SiteRule(
        name='GitHub',
        domains=('github.com',),
        selectors=('article', 'article.markdown-body', '#readme', '.markdown-body', 'main'),
        remove_selectors=('.Header', '.js-header-wrapper', '.Layout-sidebar', '.footer', '.application-main nav'),
        min_length=120,
        title_selectors=('h1', 'strong[itemprop="name"]', '.markdown-title'),
    ),
    SiteRule(
        name='The Register',
        domains=('theregister.com',),
        selectors=('article', '#body', '.article_body', '.body', 'main'),
        remove_selectors=(
            '.newsletter', '.newsletter-signup', '.subscribe', '.subscription', '.cookie', '.cookies',
            '.cookie-banner', '.ad', '.advertisement', '.related', '.share', '.social',
        ),
        min_length=500,
        title_selectors=('article h1', 'h1', '.article h1'),
    ),
    SiteRule(
        name='TechCrunch',
        domains=('techcrunch.com',),
        selectors=('article', '.article-content', '.entry-content', '.wp-block-post-content', 'main'),
        remove_selectors=(
            '.subscribe', '.subscription', '.newsletter', '.cookie', '.cookies', '.cookie-banner',
            '.ad', '.advertisement', '.social-share', '.related', '.sidebar',
        ),
        min_length=500,
        title_selectors=('article h1', 'h1', '.wp-block-post-title'),
    ),
    SiteRule(
        name='BBC',
        domains=('bbc.com', 'bbc.co.uk'),
        selectors=('article', 'main', '[data-component="text-block"]', '[data-testid="article"]'),
        remove_selectors=(
            '[data-component="ad-slot"]', '[data-testid="socialShare"]', '.share', '.promo',
            '.related', '.cookie', '.cookies', '.newsletter', '.subscribe',
        ),
        min_length=500,
        title_selectors=('h1', '[data-testid="headline"]'),
    ),
    SiteRule(
        name='DEV Community',
        domains=('dev.to',),
        selectors=('article', '#article-body', '.crayons-article__body', 'main'),
        remove_selectors=(
            '.crayons-subscription', '.crayons-article__cover', '.js-billboard-container',
            '.subscribe', '.newsletter', '.cookie', '.comments', '#comments', '.reaction-actions',
        ),
        min_length=300,
        title_selectors=('h1', '.crayons-article__header h1'),
    ),
    SiteRule(
        name='Reuters',
        domains=('reuters.com',),
        selectors=('article', 'main', '[data-testid="paragraph"]', '.article-body__content__17Yit'),
        remove_selectors=(
            '[data-testid="SignUp"]', '[data-testid="newsletter"]', '.newsletter', '.subscribe',
            '.cookie', '.cookies', '.ad', '.advertisement', '.related', '.share',
        ),
        min_length=500,
        title_selectors=('h1', '[data-testid="Heading"]'),
    ),
    SiteRule(
        name='Hacker News',
        domains=('news.ycombinator.com',),
        selectors=('.fatitem .toptext', '.toptext'),
        remove_selectors=(
            '.comment-tree', '.comment', '.subtext', '.votelinks', '.reply', '.replylink',
            '.comhead', '.sitebit', '.hnuser', '.age', '.score',
        ),
        min_length=80,
        title_selectors=('.titleline > a', 'span.titleline > a', '.athing .title a', 'title'),
    ),
    SiteRule(
        name='Product Hunt',
        domains=('producthunt.com',),
        selectors=(
            'main section[class*="productHero"]',
            'main section[class*="ProductHero"]',
            'main [class*="productHero"]',
            'main [class*="ProductHero"]',
            'main article',
            'main section',
            'main',
        ),
        remove_selectors=(
            '.comments', '[class*="comment"]', '[class*="Comment"]', '[data-test*="comment"]',
            '[data-testid*="comment"]', '[data-test*="discussion"]', '[data-testid*="discussion"]',
            '[class*="discussion"]', '[class*="Discussion"]', '.newsletter', '.subscribe', '.cookie', '.cookies',
            '.related', '.share', '.social', '[class*="modal"]', '[class*="Modal"]',
        ),
        min_length=120,
        title_selectors=('h1', '[data-test="post-name"]', '[data-testid="post-name"]'),
    ),
)


def normalize_domain(url_or_domain: str) -> str:
    parsed = urlparse(url_or_domain)
    host = parsed.netloc if parsed.netloc else url_or_domain.split('/')[0]
    return host.lower().removeprefix('www.')


def get_site_rule(url_or_domain: str) -> SiteRule | None:
    domain = normalize_domain(url_or_domain)
    for rule in SITE_RULES:
        if any(domain == registered or domain.endswith(f'.{registered}') for registered in rule.domains):
            return rule
    return None


def is_waf_blocked(url_or_domain: str) -> bool:
    """Check if a URL belongs to a WAF-protected domain that cannot be fetched."""
    domain = normalize_domain(url_or_domain)
    return any(domain == registered or domain.endswith(f'.{registered}') for registered in WAF_BLOCKED_DOMAINS)
