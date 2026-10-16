"""Conditional feed requests acknowledge only committed representations."""
from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import json

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from api.models import FeedState
from api.services.article_identity import normalize_article_url
from api.services.article_fetcher.validators import VALIDATOR_VERSION
from api.services.source_policy import policy_for_key, approved_feed_endpoint


@dataclass(frozen=True)
class FeedRequestState:
    state_id: int
    source_key: str
    feed_url: str
    request_url: str
    expected_revision: int
    policy_version: str
    headers: tuple[tuple[str, str], ...]
    reliable_checkpoint: bool
    next_poll_at: object = None
    legacy_token: object = None


# Only presentation and scheduling fields are excluded. New policy fields
# participate by default so a future content/access rule cannot silently reuse
# validators for a representation admitted under an older contract.
PRESENTATION_FIELDS = frozenset({'description', 'poll_seconds', 'request_interval'})


def policy_signature(source_key, *, window_days=30, admitted=True):
    policy = policy_for_key(source_key)
    if policy is None:
        raise ValueError('unknown_source')
    contract = {key: value for key, value in asdict(policy).items() if key not in PRESENTATION_FIELDS}
    contract.update(
        validator=VALIDATOR_VERSION, window_days=window_days, admitted=bool(admitted),
        structured=bool(getattr(settings, 'STRUCTURED_BODY_INGEST_ENABLED', False) and
                        source_key in getattr(settings, 'STRUCTURED_BODY_SOURCE_KEYS', ())),
        auto_enqueue=bool(getattr(settings, 'FULL_CONTENT_AUTO_ENQUEUE_ENABLED', False) and
                          source_key in getattr(settings, 'FULL_CONTENT_AUTO_SOURCE_KEYS', ())),
    )
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def prepare_feed_request(source_key, feed_url, *, window_days=30, admitted=True):
    from api.rss.legacy_fencing import capture_source_token
    from api.rss.legacy_fencing import fenced_source
    legacy_token = capture_source_token(source_key, include_articles=False)
    with fenced_source(legacy_token):
        return _prepare_feed_request(source_key, feed_url, legacy_token, window_days=window_days, admitted=admitted)


def _prepare_feed_request(source_key, feed_url, legacy_token, *, window_days=30, admitted=True):
    feed_url = normalize_article_url(feed_url, max_length=1024, require_article=False)
    policy = policy_for_key(source_key)
    if policy is None or not approved_feed_endpoint(source_key, policy.feed_url or feed_url, feed_url):
        raise ValueError('unapproved_feed_endpoint')
    signature = policy_signature(source_key, window_days=window_days, admitted=admitted)
    state, _ = FeedState.objects.get_or_create(
        source_key=source_key,
        feed_url=feed_url,
        config_version=policy.contract_version,
    )
    for _ in range(3):
        if state.policy_version == signature:
            break
        updated = FeedState.objects.filter(pk=state.pk, revision=state.revision).update(
            etag='', last_modified='', policy_version=signature,
            validated_effective_url='', last_success_at=None, next_poll_at=None,
            revision=F('revision') + 1,
        )
        state.refresh_from_db()
        if updated:
            break
    if state.policy_version != signature:
        raise ValueError('feed_state_conflict')
    endpoint = state.validated_effective_url or feed_url
    if not approved_feed_endpoint(source_key, feed_url, endpoint):
        raise ValueError('unapproved_feed_endpoint')
    headers = []
    if state.last_success_at is not None:
        if state.etag:
            headers.append(('If-None-Match', state.etag))
        if state.last_modified:
            headers.append(('If-Modified-Since', state.last_modified))
    FeedState.objects.filter(pk=state.pk, revision=state.revision).update(last_checked_at=timezone.now())
    return FeedRequestState(state.pk, source_key, feed_url, endpoint, state.revision, signature,
                            tuple(headers), state.last_success_at is not None, state.next_poll_at, legacy_token)


def _query(context):
    return FeedState.objects.filter(pk=context.state_id, revision=context.expected_revision, policy_version=context.policy_version)


def _commit_feed_checkpoint(context, *, etag='', last_modified='', effective_url=None):
    endpoint = effective_url or context.request_url
    if not approved_feed_endpoint(context.source_key, context.feed_url, endpoint):
        raise ValueError('unapproved_feed_endpoint')
    now = timezone.now()
    return _query(context).update(
        etag=etag, last_modified=last_modified, validated_effective_url=endpoint,
        last_checked_at=now, last_success_at=now,
        next_poll_at=now + timedelta(seconds=policy_for_key(context.source_key).poll_seconds),
        revision=F('revision') + 1,
    ) == 1


def _accept_not_modified(context, *, effective_url):
    if not context.reliable_checkpoint or not context.headers or effective_url != context.request_url:
        _query(context).update(etag='', last_modified='', validated_effective_url='', last_success_at=None,
                               next_poll_at=timezone.now(), revision=F('revision') + 1)
        return False
    now = timezone.now()
    return _query(context).update(last_checked_at=now, last_success_at=now,
                                 next_poll_at=now + timedelta(seconds=policy_for_key(context.source_key).poll_seconds),
                                 revision=F('revision') + 1) == 1


def _defer_feed(context, *, next_poll_at=None):
    return _query(context).update(last_checked_at=timezone.now(),
                                 next_poll_at=next_poll_at or timezone.now() + timedelta(seconds=60)) == 1


def _fenced_checkpoint(function, context, **kwargs):
    from api.rss.legacy_fencing import fenced_source
    from api.rss.content_store import StaleWrite
    try:
        with fenced_source(context.legacy_token):
            return function(context, **kwargs)
    except StaleWrite:
        return False


def commit_feed_checkpoint(context, **kwargs):
    return _fenced_checkpoint(_commit_feed_checkpoint, context, **kwargs)


def accept_not_modified(context, **kwargs):
    return _fenced_checkpoint(_accept_not_modified, context, **kwargs)


def defer_feed(context, **kwargs):
    return _fenced_checkpoint(_defer_feed, context, **kwargs)
