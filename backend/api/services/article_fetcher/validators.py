from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import urlparse

from .site_rules import get_site_rule, normalize_domain


class ValidationResult:
    def __init__(self, ok: bool, score: float = 0.0, reasons: list[str] | None = None):
        self.ok = ok
        self.score = score
        self.reasons = reasons or []


def _normalize(text: str) -> str:
    return ' '.join((text or '').lower().split())


def _similarity(a: str, b: str) -> float:
    a_norm = _normalize(a)
    b_norm = _normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _same_domain(url: str, canonical_url: str) -> bool:
    if not canonical_url:
        return True
    source_domain = normalize_domain(url)
    canonical_domain = normalize_domain(canonical_url)
    if not source_domain or not canonical_domain:
        return False
    if source_domain == canonical_domain:
        return True
    rule = get_site_rule(url)
    if not rule:
        return False
    allowed_domains = {
        normalize_domain(domain)
        for domain in rule.allowed_canonical_domains
    }
    return canonical_domain in allowed_domains


def validate_markdown(
    markdown: str,
    expected_title: str | None = None,
    extracted_title: str | None = None,
    url: str | None = None,
    canonical_url: str | None = None,
    summary: str | None = None,
    min_chars: int = 300,
) -> ValidationResult:
    """Validate that markdown looks like a real article body, not a summary.

    The validator is intentionally conservative: false negatives are OK because
    a user can retry or we can add a domain extractor; false positives pollute
    `full_content` and break reading/translation/TTS/chat.
    """
    reasons: list[str] = []
    body = (markdown or '').strip()
    body_norm = _normalize(body)

    if len(body) < min_chars:
        reasons.append('too_short')

    if summary:
        summary_norm = _normalize(summary)
        if summary_norm and body_norm:
            sim = _similarity(body_norm[: max(len(summary_norm) + 100, 200)], summary_norm)
            if sim > 0.82 and len(body_norm) < len(summary_norm) * 2.5:
                reasons.append('summary_sized')

    if expected_title and extracted_title:
        title_score = _similarity(expected_title, extracted_title)
        # Some aggregator titles differ slightly from page titles; be lenient.
        if title_score < 0.18 and expected_title.lower() not in body.lower():
            reasons.append('title_mismatch')

    if url and canonical_url and not _same_domain(url, canonical_url):
        reasons.append('canonical_domain_mismatch')

    if body.lower().count('subscribe') + body.lower().count('newsletter') > 12:
        reasons.append('too_much_page_chrome')

    score = 1.0
    score -= 0.25 * len(reasons)
    if len(body) > 1200:
        score += 0.1
    score = max(0.0, min(1.0, score))
    return ValidationResult(ok=not reasons, score=score, reasons=reasons)


from dataclasses import dataclass
from datetime import datetime
import re

from api.services.article_identity import InvalidIdentity, normalize_article_url, same_article_identity, validate_upstream_id
from api.services.source_policy import candidate_contract_allows, html_candidate_contract_allows
from .types import FullContentCandidate

VALIDATOR_VERSION = 'ingestion-1'


@dataclass(frozen=True)
class CandidateValidation:
    ok: bool
    markdown: str = ''
    error_code: str = ''
    score: float = 0.0


def validate_candidate(candidate: FullContentCandidate, *, expected_url: str, expected_title: str = '', summary: str | None = None) -> CandidateValidation:
    """Identity and completeness are gates; length is only a diagnostic score."""
    from bs4 import BeautifulSoup
    from .extractors import html_fragment_to_markdown, extract_markdown_from_html
    if not isinstance(candidate, FullContentCandidate):
        return CandidateValidation(False, error_code='invalid_identity')
    strings = ('source_key', 'source_item_id', 'target_url', 'retrieved_from_url', 'title', 'content_kind', 'body_field', 'content_format', 'declared_completeness', 'raw_content')
    if (any(not isinstance(getattr(candidate, name), str) for name in strings) or
            not isinstance(candidate.request_started_at, datetime) or
            (candidate.source_modified_at is not None and not isinstance(candidate.source_modified_at, datetime)) or
            (candidate.source_version is not None and not isinstance(candidate.source_version, str)) or
            (candidate.expected_revision is not None and (type(candidate.expected_revision) is not int or candidate.expected_revision < 0))):
        return CandidateValidation(False, error_code='invalid_identity')
    try:
        target = normalize_article_url(candidate.target_url)
        validate_upstream_id(candidate.source_item_id)
        normalize_article_url(candidate.retrieved_from_url, max_length=2048, require_article=False)
    except InvalidIdentity:
        return CandidateValidation(False, error_code='invalid_identity')
    if not same_article_identity(target, expected_url):
        return CandidateValidation(False, error_code='body_mismatch')
    if not (candidate_contract_allows(candidate) or html_candidate_contract_allows(candidate)):
        return CandidateValidation(False, error_code='unsupported')
    if candidate.request_started_at.tzinfo is None or (candidate.source_modified_at and candidate.source_modified_at.tzinfo is None):
        return CandidateValidation(False, error_code='invalid_identity')
    if candidate.declared_completeness != 'full':
        return CandidateValidation(False, error_code='body_partial')
    raw = candidate.raw_content
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2 * 1024 * 1024:
        return CandidateValidation(False, error_code='unsupported')
    # Inspect truncation and challenge evidence before removing page/fragment chrome.
    soup = BeautifulSoup(raw, 'html.parser') if candidate.content_format == 'html' else None
    text = soup.get_text(' ', strip=True) if soup else raw
    lowered = ' '.join(text.lower().split())
    if (re.search(r'(subscribe|sign in|log in|purchase|register).{0,60}(to (continue|read|unlock)|remaining article|full article)', lowered) or
            re.search(r'(read|continue reading).{0,30}(the rest|full article|on the website)', lowered) or
            re.search(r'(verify (you are|that you are) human|checking your browser|access denied|enable javascript and cookies)', lowered)):
        return CandidateValidation(False, error_code='body_partial')
    if soup and (soup.select_one('[class*="paywall"], [class*="truncat"], [data-paywall]') or
                 soup.select_one('form input[type="password"]')):
        return CandidateValidation(False, error_code='body_partial')
    canonical = candidate.declared_canonical_url
    # DEV cross-publisher canonical is attribution, not a target identity change.
    if canonical and candidate.source_key != 'devto' and not same_article_identity(target, canonical, allow_host_alias=True):
        return CandidateValidation(False, error_code='body_mismatch')
    if candidate.body_field == 'article_html':
        extracted = extract_markdown_from_html(raw, target)
        if not extracted.title or not extracted.canonical_url:
            return CandidateValidation(False, error_code='body_mismatch')
        if not same_article_identity(target, extracted.canonical_url, allow_host_alias=True):
            return CandidateValidation(False, error_code='body_mismatch')
        body, title = extracted.markdown, extracted.title
    elif candidate.content_format == 'html':
        body = html_fragment_to_markdown(raw, target, remove_selectors=('.medium-feed-link', '.medium-feed-footer', '.feed-footer'))
        title = candidate.title
    else:
        body, title = raw.strip(), candidate.title
    if not body.strip() or not re.search(r'\w', body):
        return CandidateValidation(False, error_code='body_empty')
    if not title or (expected_title and _similarity(title, expected_title) < 0.55):
        return CandidateValidation(False, error_code='body_mismatch')
    if summary and _normalize(summary) == _normalize(body):
        return CandidateValidation(False, error_code='body_partial')
    return CandidateValidation(True, markdown=body, score=1.0)
