"""Business authority must not imply staff access or survive revocation."""
import uuid
import pytest
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True)
INSTANCE = 'be22a55a-11c1-4ae4-9038-c919ec75aa42'

@pytest.fixture
def people(monkeypatch):
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', INSTANCE)
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    User = get_user_model()
    return User.objects.create_superuser('admin', password='synthetic'), User.objects.create_user('reviewer')

def test_grant_does_not_change_staff_flags(people):
    from api.rss.review_permissions import change_reviewer, rss_capabilities
    admin, reviewer = people
    result = change_reviewer(admin, reviewer.username, True, None, 'grant')
    reviewer.refresh_from_db()
    assert not reviewer.is_staff and not reviewer.is_superuser
    assert rss_capabilities(reviewer)['review_public_rss'] is True
    assert result['version'] == 1
    client = APIClient(); client.force_authenticate(reviewer)
    assert client.get('/api/auth/me/').data['rss_capabilities']['review_public_rss'] is True

def test_regrant_invalidates_captured_authority(people):
    from api.rss.review_permissions import change_reviewer, review_authority, assert_review_authority
    admin, reviewer = people
    change_reviewer(admin, reviewer.username, True, None, 'grant')
    authority = review_authority(reviewer)
    change_reviewer(admin, reviewer.username, False, 1, 'revoke')
    change_reviewer(admin, reviewer.username, True, 2, 'regrant')
    assert review_authority(reviewer).version == 3
    with pytest.raises(PermissionDenied): assert_review_authority(reviewer, authority)

def test_inactive_and_other_instance_fail_closed(people, monkeypatch):
    from api.rss.review_permissions import change_reviewer, rss_capabilities
    admin, reviewer = people
    change_reviewer(admin, reviewer.username, True, None, 'grant')
    reviewer.is_active = False; reviewer.save()
    assert not rss_capabilities(reviewer)['review_public_rss']
    reviewer.is_active = True; reviewer.save()
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    assert not rss_capabilities(reviewer)['review_public_rss']

def test_grant_idempotency_and_authority_boundaries(people):
    from api.rss.review_permissions import change_reviewer
    from api.rss.http import RssConflict
    from api.rss.review_models import RssReviewerEvent
    admin, reviewer = people
    change_reviewer(admin, reviewer.username, True, None, 'grant')
    assert change_reviewer(admin, reviewer.username, True, None, 'grant')['version'] == 1
    assert RssReviewerEvent.objects.count() == 1
    with pytest.raises(RssConflict): change_reviewer(admin, reviewer.username, False, 1, 'grant')
    with pytest.raises(PermissionDenied): change_reviewer(reviewer, admin.username, True, None, 'escalate')
