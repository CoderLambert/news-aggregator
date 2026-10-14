from dataclasses import replace
import pytest
from api.services.feed_state import policy_signature, prepare_feed_request, commit_feed_checkpoint
from api.services.source_policy import POLICIES
from api.models import FeedState


def test_description_and_polling_cadence_do_not_invalidate_body_contract(monkeypatch):
    original = POLICIES['webkit']
    before = policy_signature('webkit')
    monkeypatch.setitem(POLICIES, 'webkit', replace(original, description='A new display description', poll_seconds=1200, request_interval=2.0))
    assert policy_signature('webkit') == before


@pytest.mark.parametrize('change', [
    {'body_fields': ()}, {'html_allowed': False}, {'unsupported_reason': 'permission_pending'},
    {'keyword_filter': 'new_energy'}, {'contract_version': 'changed'}, {'date_timezone': 'UTC'},
])
def test_semantic_admission_changes_still_invalidate(monkeypatch, change):
    original = POLICIES['webkit']; before = policy_signature('webkit')
    monkeypatch.setitem(POLICIES, 'webkit', replace(original, **change))
    assert policy_signature('webkit') != before


@pytest.mark.django_db
def test_display_edit_preserves_committed_conditional_checkpoint(monkeypatch):
    context = prepare_feed_request('webkit', POLICIES['webkit'].feed_url)
    assert commit_feed_checkpoint(context, etag='"approved-body"', effective_url=context.request_url)
    before = FeedState.objects.get(pk=context.state_id)
    monkeypatch.setitem(POLICIES, 'webkit', replace(POLICIES['webkit'], description='Presentation only'))
    next_request = prepare_feed_request('webkit', POLICIES['webkit'].feed_url)
    after = FeedState.objects.get(pk=context.state_id)
    assert ('If-None-Match', '"approved-body"') in next_request.headers
    assert after.revision == before.revision and after.last_success_at == before.last_success_at
