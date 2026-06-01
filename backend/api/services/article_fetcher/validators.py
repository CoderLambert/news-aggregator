from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import urlparse


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
    try:
        a = urlparse(url).netloc.lower().removeprefix('www.')
        b = urlparse(canonical_url).netloc.lower().removeprefix('www.')
        return not a or not b or a == b
    except Exception:
        return True


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
