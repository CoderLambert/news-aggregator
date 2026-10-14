"""Short, idempotent item transactions, with no network or AI side effects."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from api.models import Category, News, NewsSourceItem, Source
from api.services.article_identity import InvalidIdentity, normalize_article_url, validate_upstream_id
from api.services.article_fetcher.types import FullContentCandidate
from api.services.article_fetcher.validators import validate_candidate
from api.services.full_content_status import commit_candidate, enqueue_fetch
from api.services.source_policy import POLICIES, policy_for_name
from api.services.article_metadata import can_promote_publisher


@dataclass(frozen=True)
class IngestResult:
    news_id: int | None
    receipt_outcome: str
    reason: str = ''
    changed: bool = False
    body_committed: bool = False


def ingest_item(item, *, source_defaults=None) -> IngestResult:
    # Reject invalid titles before *any* transaction, identity correction or
    # candidate validation. A malformed feed item must not quarantine an
    # already-read article or advance its source mapping.
    title = item.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        return IngestResult(None, 'policy_skip', 'invalid_identity')
    policy = POLICIES.get(item['source_key']) if item.get('source_key') else policy_for_name(item.get('source_name', ''))
    if not policy or policy.unsupported_reason:
        return IngestResult(None, 'policy_skip', policy.unsupported_reason if policy else 'unsupported')
    try:
        url = normalize_article_url(item.get('url', ''))
        upstream_id = validate_upstream_id(str(item.get('upstream_id') or url))
        discovery = normalize_article_url(item.get('discovery_url') or url, max_length=1024, require_article=False)
        if urlsplit(url).hostname not in policy.domains and policy.key != 'hackernews':
            raise InvalidIdentity('invalid_publisher_url')
    except InvalidIdentity as error:
        return IngestResult(None, 'policy_skip', str(error))
    kind = item.get('content_kind') or policy.content_kind
    if kind not in dict(News.CONTENT_KIND_CHOICES):
        return IngestResult(None, 'policy_skip', 'invalid_identity')
    # Validate raw candidates before opening a transaction. Revalidate against
    # resolved identity/version at the CAS boundary, never trust item booleans.
    candidate = item.get('body_candidate')
    body_reason = ''
    if candidate is not None:
        if (not isinstance(candidate, FullContentCandidate) or candidate.source_key != policy.key or
                candidate.source_item_id != upstream_id or candidate.content_kind != kind):
            body_reason = 'invalid_identity'
            candidate = None
        else:
            validation = validate_candidate(candidate, expected_url=url, expected_title=item['title'], summary=item.get('summary'))
            if not validation.ok:
                body_reason = validation.error_code
                candidate = None
    for attempt in range(3):
        try:
            return _ingest_transaction(item, policy, url, upstream_id, discovery, kind, candidate,
                                       body_reason, source_defaults or {})
        except IntegrityError:
            # Retry only database identity resolution, not fetching. A unique
            # source ID or exact URL may have been created by another process.
            if attempt == 2:
                raise
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ('locked', 'busy')):
                raise
            if attempt == 2:
                return IngestResult(None, 'deferred', 'persistence_conflict')
        time.sleep(0.01 * (attempt + 1))
    raise AssertionError('unreachable')


@transaction.atomic
def _ingest_transaction(item, policy, url, upstream_id, discovery, kind, candidate, body_reason, source_defaults):
    seen = timezone.now()
    # This write acquires SQLite's writer reservation before identity reads,
    # avoiding select_for_update's illusory row locks on SQLite.
    NewsSourceItem.objects.filter(source_key=policy.key, upstream_id=upstream_id).update(last_seen_at=seen)
    source, _ = Source.objects.get_or_create(name=policy.name, defaults={**source_defaults, 'region': policy.region})
    source_updates = {}
    if source_defaults.get('language') and source.language != source_defaults['language']:
        source_updates['language'] = source_defaults['language']
    if not source.source_type and source_defaults.get('source_type'):
        source_updates['source_type'] = source_defaults['source_type']
    if source_updates:
        Source.objects.filter(pk=source.pk).update(**source_updates)
    category, _ = Category.objects.get_or_create(
        name=item['category_name'], defaults={'slug': item['category_name'].lower().replace(' ', '-')},
    )
    mapping = NewsSourceItem.objects.filter(source_key=policy.key, upstream_id=upstream_id).first()
    news = mapping.news if mapping else News.objects.filter(url=url).first()
    if news and news.url != url:
        # A shared article's URL belongs to its primary publisher, not every
        # discovery feed which points at it. Never quarantine good publisher
        # text because a secondary/HN editorial link changes its target.
        owns_primary = news.source_id == source.pk
        publisher_identity = policy.key != 'hackernews' or (
            urlsplit(news.url).hostname in policy.domains and
            urlsplit(url).hostname in policy.domains
        )
        if not owns_primary or not publisher_identity:
            return IngestResult(None, 'policy_skip', 'identity_conflict')
        if News.objects.filter(url=url).exclude(pk=news.pk).exists():
            return IngestResult(news.pk, 'policy_skip', 'identity_conflict')
        from api.services.full_content_status import correct_article_identity
        if not correct_article_identity(news, url, expected_url=news.url, expected_revision=news.full_content_revision):
            return IngestResult(news.pk, 'deferred', 'persistence_conflict')
    inferred = item.get('publish_time_inferred', item.get('publish_time') is None)
    published = item.get('publish_time')
    if published is not None and timezone.is_naive(published):
        # Old spiders supplied local-naive values. Treat them conservatively as
        # inferred until T05/T07 move each adapter to timezone-preserving parsing.
        published = timezone.make_aware(published)
        inferred = True
    summary = item.get('summary', item.get('content', '')) or ''
    title = item['title']
    updates = {'title': title, 'content': summary, 'content_kind': kind,
               'title_hash': int(hashlib.md5(title.lower().strip().encode()).hexdigest()[:8], 16)}
    for field in ('author', 'cover_image'):
        if item.get(field):
            updates[field] = item[field]
    if published is not None and not inferred:
        updates['publish_time'] = published
    promotion = news is not None and can_promote_publisher(news, policy, url, kind)
    promoted_from = news.source_id if promotion else None
    changed = False
    if news is None:
        news = News.objects.create(
            **updates, **({} if 'publish_time' in updates else {'publish_time': published or seen}),
            url=url, source=source, category=category,
        )
        changed = True
    elif news.source_id == source.pk or promotion:
        if promotion:
            updates.update(source_id=source.pk, title_zh='', content_zh='',
                author=item.get('author') or '', cover_image=item.get('cover_image') or '',
                suggested_questions=[], suggested_questions_generated_at=None,
                translation_status='pending', translation_error='', translation_retry_count=0)
        # Follow corrections to the publisher's own category policy without
        # modifying classifications supplied by secondary discovery sources.
        updates['category_id'] = category.pk
        changed = any(getattr(news, key) != value for key, value in updates.items())
        if News.objects.filter(pk=news.pk, url=news.url, full_content_revision=news.full_content_revision).update(**updates) != 1:
            return IngestResult(news.pk, 'deferred', 'persistence_conflict')
        news.refresh_from_db()
    metadata = dict(mapping.metadata or {}) if mapping else {}
    if promotion:
        metadata['publisher_promotion'] = {'from_source_id': promoted_from, 'from_source_key': 'hackernews', 'at': seen.isoformat()}
    metadata.update({'publish_time_inferred': bool(inferred), 'category_name': item['category_name']})
    if published is not None and not inferred:
        metadata['source_publish_time'] = published.isoformat()
    if item.get('source_modified_at'):
        metadata['source_modified_at'] = item['source_modified_at'].isoformat()
    if item.get('source_version'):
        metadata['source_version'] = str(item['source_version'])
    if policy.feed_url:
        metadata['feed_url'] = policy.feed_url
    if mapping:
        NewsSourceItem.objects.filter(pk=mapping.pk).update(discovery_url=discovery, metadata=metadata, last_seen_at=seen)
    else:
        NewsSourceItem.objects.create(source_key=policy.key, upstream_id=upstream_id, news=news,
                                      discovery_url=discovery, metadata=metadata, last_seen_at=seen)
    body_committed = False
    reason = body_reason
    enabled = getattr(settings, 'STRUCTURED_BODY_INGEST_ENABLED', False)
    allowed = getattr(settings, 'STRUCTURED_BODY_SOURCE_KEYS', ())
    if candidate is not None and enabled and policy.key in allowed:
        committed = commit_candidate(news, candidate, summary=item.get('summary'))
        if committed.outcome == 'conflict':
            # Roll back metadata/mapping too. A receipt cannot acknowledge this
            # candidate until reevaluation against the latest evidence succeeds.
            transaction.set_rollback(True)
            return IngestResult(news.pk, 'deferred', 'persistence_conflict')
        reason = committed.reason
        body_committed = committed.changed
        changed = changed or committed.changed
    elif candidate is not None:
        reason = 'structured_body_disabled'
    if (getattr(settings, 'FULL_CONTENT_AUTO_ENQUEUE_ENABLED', False) and
            policy.key in getattr(settings, 'FULL_CONTENT_AUTO_SOURCE_KEYS', ()) and
            not inferred and published is not None and seen - timedelta(days=7) <= published <= seen and kind == 'article'):
        enqueue_fetch(news)
    return IngestResult(news.pk, 'committed', reason, changed, body_committed)
