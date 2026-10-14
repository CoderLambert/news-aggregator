"""Record incomparable publisher revisions without replacing readable text.

The receipt holds hashes/identities only, not another raw-body cache. Any
verification uses the existing permission checks, worker lease and budgets.
"""
import hashlib
from django.conf import settings
from django.utils import timezone
from api.models import NewsSourceItem
from api.services.article_fetcher.validators import validate_candidate
from api.services.full_content_status import enqueue_fetch, has_full_content


def record_incomparable_body(news, source_item, candidate):
    if not has_full_content(news):
        return None
    old = news.full_content_provenance or {}
    if (old.get('source_key') != candidate.source_key or
            old.get('source_item_id') != candidate.source_item_id or
            (old.get('source_modified_at') and candidate.source_modified_at) or
            (old.get('source_version') and old.get('source_version') == candidate.source_version)):
        return None
    validation = validate_candidate(candidate, expected_url=news.url, expected_title=news.title)
    if not validation.ok:
        return None
    body_hash = hashlib.sha256(validation.markdown.encode()).hexdigest()
    if body_hash == hashlib.sha256(news.full_content.encode()).hexdigest():
        return None
    metadata = dict(source_item.metadata or {})
    previous = metadata.get('body_review') or {}
    if previous.get('candidate_sha256') == body_hash and previous.get('base_revision') == news.full_content_revision:
        return previous
    review = {
        'status': 'pending_review', 'candidate_sha256': body_hash,
        'base_revision': news.full_content_revision, 'detected_at': timezone.now().isoformat(),
        'source_key': candidate.source_key, 'source_item_id': candidate.source_item_id,
    }
    # Do not start workers or enable sources. Only an existing, explicitly
    # enabled auto-fetch source may enqueue a bounded verification intent.
    if (getattr(settings, 'FULL_CONTENT_AUTO_ENQUEUE_ENABLED', False) and
            candidate.source_key in getattr(settings, 'FULL_CONTENT_AUTO_SOURCE_KEYS', ())):
        review['queue_result'] = enqueue_fetch(news, force=True)
    else:
        review['queue_result'] = 'operator_review_required'
    metadata['body_review'] = review
    NewsSourceItem.objects.filter(pk=source_item.pk, news_id=news.pk).update(metadata=metadata)
    source_item.metadata = metadata
    return review


def review_status(news):
    """Read-only public status. No candidate text, URL tokens or private keys."""
    reviews = []
    for item in news.source_items.all():
        review = (item.metadata or {}).get('body_review')
        if not isinstance(review, dict):
            continue
        revision = review.get('base_revision')
        if not isinstance(revision, int):
            continue
        resolved = news.full_content_revision > revision
        reviews.append({'status': 'reviewed' if resolved else 'pending_review',
                        'source_key': item.source_key, 'detected_at': review.get('detected_at'),
                        'base_revision': revision, 'queue_result': review.get('queue_result')})
    return reviews
