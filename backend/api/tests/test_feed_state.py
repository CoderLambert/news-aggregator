from dataclasses import replace
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from api.models import FeedState
from api.services.feed_state import (
    prepare_feed_request, commit_feed_checkpoint, accept_not_modified, defer_feed, policy_signature,
)


@pytest.mark.django_db
def test_headers_are_empty_until_representation_commits_and_cas_fences_old_response():
    first = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    assert first.headers == () and not first.reliable_checkpoint
    state = FeedState.objects.get(pk=first.state_id)
    assert state.etag == ''
    assert commit_feed_checkpoint(first, etag='"opaque-z"', last_modified='Tue, 13 Oct 2026 00:00:00 GMT')
    assert not commit_feed_checkpoint(first, etag='old')
    current = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    assert dict(current.headers)['If-None-Match'] == '"opaque-z"'
    assert current.reliable_checkpoint
    assert accept_not_modified(current, effective_url=current.request_url)


@pytest.mark.django_db
def test_first_304_does_not_claim_unchanged_or_skip_unpersisted_entries():
    context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    assert not accept_not_modified(context, effective_url=context.request_url)
    state = FeedState.objects.get(pk=context.state_id)
    assert state.etag == '' and state.last_success_at is None
    assert state.next_poll_at <= timezone.now()


@pytest.mark.django_db
def test_body_enable_change_invalidates_etag_and_poll_without_changing_other_sources():
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=False):
        context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
        assert commit_feed_checkpoint(context, etag='old')
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'webkit'}):
        enabled = prepare_feed_request('webkit', 'https://webkit.org/feed/')
        signature = enabled.policy_version
        assert enabled.headers == () and enabled.next_poll_at is None
        assert not enabled.reliable_checkpoint
        with override_settings(STRUCTURED_BODY_SOURCE_KEYS={'webkit', 'devto'}):
            assert policy_signature('webkit') == signature
    assert not commit_feed_checkpoint(context, etag='obsolete-policy')


@pytest.mark.django_db
def test_failure_keeps_committed_headers_and_does_not_overwrite_new_checkpoint():
    context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    assert commit_feed_checkpoint(context, etag='stable')
    latest = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    retry_at = timezone.now() + timedelta(hours=2)
    assert defer_feed(latest, next_poll_at=retry_at)
    assert FeedState.objects.get(pk=context.state_id).etag == 'stable'
    assert not defer_feed(context)
    assert FeedState.objects.get(pk=context.state_id).next_poll_at == retry_at


@pytest.mark.django_db
def test_validated_redirect_endpoint_is_used_directly_and_unapproved_host_rejected():
    context = prepare_feed_request('infoq', 'https://www.infoq.com/feed')
    assert commit_feed_checkpoint(context, etag='version', effective_url='https://feed.infoq.com/')
    current = prepare_feed_request('infoq', 'https://www.infoq.com/feed')
    assert current.request_url == 'https://feed.infoq.com/'
    with pytest.raises(ValueError):
        commit_feed_checkpoint(current, effective_url='https://unapproved.example/feed')
    assert not accept_not_modified(current, effective_url='https://www.infoq.com/feed')
