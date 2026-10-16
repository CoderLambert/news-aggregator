"""SQLite body commit and reusable writer fence. No network or row-lock assumptions.

Callers must not rebind an existing FeedBinding to a rebuilt engine or mutate
policy/ownership without incrementing its version. Existing enclosing
transactions must retry the WHOLE transaction on SQLite busy/snapshot errors.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import re
import sqlite3
import time
import uuid

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from api.models import BodyCandidate, EngineEntryMap, FeedBinding, News, SourceFeedLink, SourcePublication
from api.rss.content import ConvertedContent, MAX_CONTENT_BYTES
from api.rss.legacy_translation import archive_changed_translations, exact_hash


SUMMARY_POLICIES = {'summary_only', 'rss_summary_only'}
BODY_POLICIES = {'standard', 'public_rss', 'public_feed', 'official_html', 'regulatory_data'}


class StaleWrite(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class WriteToken:
    news_id: int
    news_url: str
    expected_revision: int
    source_id: int
    source_owner: str
    source_epoch: int
    source_policy_version: int
    body_owner_version: int
    body_owner_source_id: int | None
    body_owner_binding_id: uuid.UUID | None
    entry_id: uuid.UUID | None = None
    engine_instance_uuid: uuid.UUID | None = None
    account_id: int | None = None
    engine_feed_id: int | None = None
    engine_entry_id: int | None = None
    binding_policy_version: int | None = None


@dataclass(frozen=True)
class CommitResult:
    status: str
    reason: str = ''
    candidate_id: uuid.UUID | None = None
    revision: int | None = None


def capture_write_token(*, news_id: int, source_id: int, entry_id=None) -> WriteToken:
    """Capture before obtaining content; this never claims an unowned article."""
    try:
        news = News.objects.get(pk=news_id)
        publication = SourcePublication.objects.get(source_id=source_id)
    except (News.DoesNotExist, SourcePublication.DoesNotExist):
        raise StaleWrite('missing_source_or_news') from None
    identity = {}
    if entry_id is not None:
        try:
            entry = EngineEntryMap.objects.select_related('binding').get(pk=entry_id)
        except EngineEntryMap.DoesNotExist:
            raise StaleWrite('missing_entry') from None
        identity = dict(entry_id=entry.pk, engine_instance_uuid=entry.binding.engine_instance_uuid,
            account_id=entry.binding.account_id, engine_feed_id=entry.binding.engine_feed_id,
            engine_entry_id=entry.engine_entry_id, binding_policy_version=entry.binding.policy_version)
    token = WriteToken(news_id=news.pk, news_url=news.url, expected_revision=news.full_content_revision,
        source_id=source_id, source_owner=publication.owner, source_epoch=publication.epoch,
        source_policy_version=publication.policy_version, body_owner_version=news.body_owner_version,
        body_owner_source_id=news.body_owner_source_id, body_owner_binding_id=news.body_owner_binding_id,
        **identity)
    _validate_fence(token, news)
    return token


def _validate_fence(token, news):
    if news.url != token.news_url or news.full_content_revision != token.expected_revision:
        raise StaleWrite('news_identity_or_revision_changed')
    if (news.body_owner_version, news.body_owner_source_id, news.body_owner_binding_id) != (
            token.body_owner_version, token.body_owner_source_id, token.body_owner_binding_id):
        raise StaleWrite('body_owner_changed')
    try:
        publication = SourcePublication.objects.get(source_id=token.source_id)
    except SourcePublication.DoesNotExist:
        raise StaleWrite('source_publication_missing') from None
    if publication.owner != token.source_owner or publication.owner not in {'legacy', 'miniflux'}:
        raise StaleWrite('source_owner_changed_or_paused')
    if publication.epoch != token.source_epoch or publication.policy_version != token.source_policy_version:
        raise StaleWrite('source_epoch_or_policy_changed')
    if publication.reading_policy not in SUMMARY_POLICIES | BODY_POLICIES:
        raise StaleWrite('unknown_reading_policy')
    if publication.owner == 'legacy':
        if (news.body_owner_source_id != token.source_id or news.body_owner_binding_id is not None
                or token.entry_id is not None):
            raise StaleWrite('legacy_not_body_owner')
        return publication
    if news.body_owner_binding_id is None or news.body_owner_source_id is not None or token.entry_id is None:
        raise StaleWrite('binding_not_body_owner')
    try:
        entry = EngineEntryMap.objects.select_related('binding').get(pk=token.entry_id)
    except EngineEntryMap.DoesNotExist:
        raise StaleWrite('entry_missing') from None
    binding = entry.binding
    if (entry.binding_id != news.body_owner_binding_id or entry.news_id != news.pk
            or entry.source_url != token.news_url or entry.engine_entry_id != token.engine_entry_id
            or entry.disposition != 'linked'):
        raise StaleWrite('entry_identity_changed')
    if (binding.engine_instance_uuid, binding.account_id, binding.engine_feed_id) != (
            token.engine_instance_uuid, token.account_id, token.engine_feed_id):
        raise StaleWrite('engine_identity_changed')
    if binding.engine_feed_id is None:
        raise StaleWrite('binding_unregistered')
    if (binding.policy_version != token.binding_policy_version
            or binding.applied_policy_version != binding.policy_version):
        raise StaleWrite('binding_policy_changed_or_unapplied')
    if not binding.desired_enabled or binding.connection_state != 'ready':
        raise StaleWrite('binding_disabled_or_unready')
    if not SourceFeedLink.objects.filter(source_id=token.source_id, binding_id=binding.pk, enabled=True).exists():
        raise StaleWrite('source_binding_disabled')
    return publication


@contextmanager
def fenced_article(token: WriteToken):
    """Yield fresh News after acquiring SQLite's writer reservation and all checks.

    T09/legacy callers can archive_changed_translations(news, replacements), then
    update source strings and returned clearing fields here. Do not do network I/O
    or hand this object to another thread. No cursor is advanced by this helper.
    """
    if connection.vendor != 'sqlite':
        raise RuntimeError('rss_writer_fence_requires_sqlite')
    with transaction.atomic():
        # Acquire the database writer reservation BEFORE any reads in this block.
        # This also serializes concurrent policy/owner/entry updates, unlike a row
        # lock on News alone. It changes neither revision nor historical hashes.
        if not News.objects.filter(pk=token.news_id).update(full_content_revision=F('full_content_revision')):
            raise StaleWrite('news_missing')
        news = News.objects.get(pk=token.news_id)
        _validate_fence(token, news)
        yield news


def _retry_sqlite_write(action):
    nested = connection.in_atomic_block
    for attempt in range(3):
        try:
            return action()
        except OperationalError as error:
            code = getattr(error.__cause__, 'sqlite_errorcode', None)
            if nested or code is None or (code & 0xff) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or attempt == 2:
                raise
            time.sleep(0.025 * (attempt + 1))


def _content_error(converted, completeness, evidence):
    if not isinstance(converted, ConvertedContent):
        return 'not_converted_content'
    if not isinstance(converted.markdown, str) or not converted.markdown.strip():
        return 'empty_content'
    if len(converted.markdown.encode('utf-8')) > getattr(settings, 'RSS_MAX_MARKDOWN_BYTES', MAX_CONTENT_BYTES):
        return 'markdown_too_large'
    if exact_hash(converted.markdown) != converted.canonical_hash:
        return 'canonical_hash_mismatch'
    if not re.fullmatch(r'[0-9a-f]{64}', converted.raw_hash or '') or not 1 <= len(converted.conversion_version) <= 128:
        return 'invalid_conversion_identity'
    if completeness not in {'unknown', 'summary', 'verified'}:
        return 'invalid_completeness'
    if completeness == 'verified' and evidence.get('verified_canonical_hash') != converted.canonical_hash:
        return 'verification_not_hash_bound'
    if converted.markdown.strip().lower() in {'access denied', '403 forbidden', '404 not found', '500 internal server error', 'service unavailable'}:
        return 'explicit_error_content'
    if evidence.get('error_code'):
        return 'explicit_error_content'
    return ''


def _identity_evidence(token):
    return dict(binding_id=str(token.body_owner_binding_id), instance_uuid=str(token.engine_instance_uuid),
                account_id=token.account_id, feed_id=token.engine_feed_id, entry_id=token.engine_entry_id)


def _candidate(token, converted, content_kind, completeness, evidence):
    identity = dict(entry_id=token.entry_id, news_id=token.news_id, source_id=token.source_id,
        source_epoch=token.source_epoch, body_owner_version=token.body_owner_version,
        source_policy_version=token.source_policy_version, binding_policy_version=token.binding_policy_version,
        canonical_hash=converted.canonical_hash, conversion_version=converted.conversion_version,
        expected_revision=token.expected_revision)
    candidate, _ = BodyCandidate.objects.get_or_create(**identity, defaults=dict(
        news_url=token.news_url, markdown=converted.markdown, raw_hash=converted.raw_hash,
        content_kind=content_kind, completeness=completeness,
        evidence={**evidence, '_write_identity': _identity_evidence(token)},
    ))
    return candidate


def _finish(candidate, status, reason, revision):
    candidate.state = status
    candidate.reason = reason
    candidate.resolved_at = None if status == 'quarantined' else timezone.now()
    candidate.save(update_fields=['state', 'reason', 'resolved_at'])
    return CommitResult(status, reason, candidate.pk, revision)


def _commit_checked(news, token, candidate, *, accept_shortening=False):
    converted = ConvertedContent(candidate.markdown, candidate.raw_hash, candidate.canonical_hash, candidate.conversion_version)
    error = _content_error(converted, candidate.completeness, candidate.evidence)
    if error:
        return _finish(candidate, 'rejected', error, news.full_content_revision)
    publication = SourcePublication.objects.get(source_id=token.source_id)
    if publication.reading_policy in SUMMARY_POLICIES and candidate.completeness != 'summary':
        return _finish(candidate, 'rejected', 'summary_only_policy', news.full_content_revision)
    # Compare actual accepted bytes, not a potentially uninitialized historical hash.
    # No-op preserves old hash/provenance/state, compatibility translations and revision.
    if exact_hash(news.full_content) == candidate.canonical_hash:
        EngineEntryMap.objects.filter(pk=token.entry_id).update(raw_hash=candidate.raw_hash,
            conversion_version=candidate.conversion_version, last_seen=timezone.now())
        return _finish(candidate, 'unchanged', '', news.full_content_revision)
    if candidate.completeness == 'summary' and (
            news.full_content_state == 'complete' or news.full_content_completeness == 'verified'):
        return _finish(candidate, 'rejected', 'summary_cannot_replace_complete', news.full_content_revision)
    minimum = int(getattr(settings, 'RSS_BODY_SHRINK_MIN_CHARS', 1000))
    ratio = float(getattr(settings, 'RSS_BODY_SHRINK_RATIO', 0.5))
    if minimum < 0 or not 0 < ratio <= 1:
        raise ValueError('invalid_body_shrink_configuration')
    if not accept_shortening and len(news.full_content) >= minimum and len(candidate.markdown) < len(news.full_content) * ratio:
        return _finish(candidate, 'quarantined', 'suspicious_shortening', news.full_content_revision)
    updates = archive_changed_translations(news, {'full_content': candidate.markdown})
    updates.update(full_content=candidate.markdown, full_content_hash=candidate.canonical_hash,
        full_content_revision=news.full_content_revision + 1, full_content_state='available',
        full_content_completeness=candidate.completeness, content_kind=candidate.content_kind,
        full_content_fetched_at=timezone.now(), full_content_fetch_status='success',
        full_content_fetch_error='', full_content_error_code='',
        full_content_provenance=dict(owner='miniflux', **_identity_evidence(token), raw_hash=candidate.raw_hash,
            canonical_hash=candidate.canonical_hash, conversion_version=candidate.conversion_version,
            source_id=token.source_id, source_epoch=token.source_epoch,
            body_owner_version=token.body_owner_version, source_policy_version=token.source_policy_version,
            binding_policy_version=token.binding_policy_version))
    News.objects.filter(pk=news.pk).update(**updates)
    EngineEntryMap.objects.filter(pk=token.entry_id).update(raw_hash=candidate.raw_hash,
        conversion_version=candidate.conversion_version, last_seen=timezone.now())
    return _finish(candidate, 'accepted', '', news.full_content_revision + 1)


def commit_body(token: WriteToken, converted: ConvertedContent, *, content_kind='article', completeness='unknown', evidence=None) -> CommitResult:
    """Submit converted content; only accepted writes increment body revision.

    Association/metadata and sync cursors belong to the caller. An existing outer
    transaction can include all of them, and must replay entirely on DB failure.
    Candidate evidence may mark explicit errors or hash-bound verification; it
    must contain safe local metadata only, never publisher HTML or credentials.
    """
    evidence = dict(evidence or {})
    if token.source_owner != 'miniflux' or token.entry_id is None:
        return CommitResult('stale', 'engine_token_required')
    def write():
        try:
            with fenced_article(token) as news:
                error = _content_error(converted, completeness, evidence)
                if error:
                    return CommitResult('rejected', error, revision=news.full_content_revision)
                if content_kind not in dict(News.CONTENT_KIND_CHOICES):
                    return CommitResult('rejected', 'invalid_content_kind', revision=news.full_content_revision)
                candidate = _candidate(token, converted, content_kind, completeness, evidence)
                if candidate.state != 'pending':
                    # Replays cannot revise a quarantined/rejected candidate's evidence
                    # or silently accept it. Explicit resolution rechecks every fence.
                    return CommitResult(candidate.state, candidate.reason, candidate.pk, news.full_content_revision)
                return _commit_checked(news, token, candidate)
        except StaleWrite as error:
            return CommitResult('stale', error.reason)
    return _retry_sqlite_write(write)


def _token_from_candidate(candidate):
    try:
        identity = candidate.evidence['_write_identity']
        return WriteToken(news_id=candidate.news_id, news_url=candidate.news_url,
            expected_revision=candidate.expected_revision, source_id=candidate.source_id,
            source_owner='miniflux', source_epoch=candidate.source_epoch,
            source_policy_version=candidate.source_policy_version, body_owner_version=candidate.body_owner_version,
            body_owner_source_id=None, body_owner_binding_id=uuid.UUID(identity['binding_id']),
            entry_id=candidate.entry_id, engine_instance_uuid=uuid.UUID(identity['instance_uuid']),
            account_id=identity['account_id'], engine_feed_id=identity['feed_id'], engine_entry_id=identity['entry_id'],
            binding_policy_version=candidate.binding_policy_version)
    except (KeyError, TypeError, ValueError):
        raise StaleWrite('candidate_identity_missing') from None


def resolve_candidate(candidate_id, *, decision: str) -> CommitResult:
    """Internal operator action; acceptance only overrides the shortening guard."""
    if decision not in {'accept', 'reject'}:
        raise ValueError('invalid_candidate_decision')

    def write():
        try:
            # Initial read captures only immutable candidate tokens. The object is
            # read again after the SQLite writer reservation before changing state.
            candidate = BodyCandidate.objects.get(pk=candidate_id)
            token = _token_from_candidate(candidate)
            with fenced_article(token) as news:
                candidate = BodyCandidate.objects.get(pk=candidate_id)
                if _token_from_candidate(candidate) != token:
                    raise StaleWrite('candidate_changed')
                if candidate.state != 'quarantined':
                    return CommitResult('conflict', 'candidate_not_quarantined', candidate.pk, news.full_content_revision)
                if decision == 'reject':
                    return _finish(candidate, 'rejected', 'operator_rejected', news.full_content_revision)
                return _commit_checked(news, token, candidate, accept_shortening=True)
        except BodyCandidate.DoesNotExist:
            return CommitResult('conflict', 'candidate_missing')
        except StaleWrite as error:
            return CommitResult('stale', error.reason, candidate_id)
    return _retry_sqlite_write(write)
