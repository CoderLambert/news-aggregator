"""Private retained uploads and batch removal use actual subscription provenance."""
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ChannelSubscription, Source
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.models import FeedOperation
from api.rss.opml import process_imports
from api.rss.subscriptions import unsubscribe
from api.tests.rss.registration_fixtures import connect_pending
from api.tests.rss.test_control_worker import lab  # noqa: F401
from api.tests.rss.test_opml_import import XML, client, confirmation, people, preview  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def imported(user):
    result = preview(user)
    assert result.status_code == 201
    assert client(user).post('/api/me/rss-imports/confirm/', confirmation(result), format='json').status_code == 202
    process_imports()
    connect_pending()
    return result.data['id']


def test_history_retains_exact_file_and_is_owner_only(people):
    a, b = people
    first = preview(a).data['id']
    preview(b)
    response = client(a).get('/api/me/rss-imports/?page=1')
    assert response.status_code == 200
    assert response.data['count'] == 1
    row = response.data['results'][0]
    assert row['id'] == first and row['filename'] == 'feeds.opml'
    assert row['file_size'] == len(XML) and row['counts']['preview'] == 2
    assert 'preview_token' not in row and 'file_content' not in row
    download = client(a).get(f'/api/me/rss-imports/{first}/file/')
    assert download.status_code == 200 and download.content == XML
    assert download['Cache-Control'] == 'private, no-store'
    assert download['X-Content-Type-Options'] == 'nosniff'
    assert 'attachment' in download['Content-Disposition']
    assert client(b).get(f'/api/me/rss-imports/{first}/file/').status_code == 404
    assert client(b).delete(f'/api/me/rss-imports/{first}/').status_code == 404
    assert APIClient().get('/api/me/rss-imports/').status_code == 401


def test_remove_only_created_subscriptions_and_keep_history_sources_and_other_owners(people):
    a, b = people
    # Existing subscription is present before A imports the same file.
    old = client(a).post('/api/me/rss-subscriptions/', {'feed_url': 'https://example.com/feed'}, format='json', HTTP_IDEMPOTENCY_KEY='existing')
    connect_pending()
    existing = ChannelSubscription.objects.get(user=a, source_id=old.data['source_id'])
    identity = imported(a)
    new = ChannelSubscription.objects.filter(user=a).exclude(pk=existing.pk).get()
    other = ChannelSubscription.objects.create(user=b, source=new.source)
    sources = set(Source.objects.values_list('pk', flat=True))
    path = f'/api/me/rss-imports/{identity}/'
    result = client(a).delete(path)
    assert result.status_code == 200
    assert result.data['status'] == 'removed'
    assert result.data['removed_at'] and result.data['removed_count'] == 1
    assert set(ChannelSubscription.objects.values_list('pk', flat=True)) == {existing.pk, other.pk}
    assert set(Source.objects.values_list('pk', flat=True)) == sources
    assert RssImportBatch.objects.filter(pk=identity).exists()
    assert client(a).get(f'{path}file/').content == XML
    assert client(a).delete(path).data['removed_count'] == 1
    assert client(a).post(path, {'selected_ids': [str(RssImportItem.objects.filter(batch_id=identity).first().pk)]}, format='json').status_code == 409


@pytest.mark.parametrize('processed', [False, True])
def test_remove_fences_pending_imports_and_inflight_completion(people, processed):
    a, _ = people
    result = preview(a)
    client(a).post('/api/me/rss-imports/confirm/', confirmation(result), format='json')
    if processed:
        process_imports()
        FeedOperation.objects.filter(actor=a).update(state='running', lease_epoch=3)
    identity = result.data['id']
    assert client(a).delete(f'/api/me/rss-imports/{identity}/').status_code == 200
    assert process_imports() == 0
    assert not FeedOperation.objects.filter(actor=a, state='running').exists()
    connect_pending()
    assert not ChannelSubscription.objects.filter(user=a).exists()
    assert client(a).post('/api/me/rss-imports/confirm/', confirmation(result), format='json').status_code == 409


def test_remove_preserves_later_resubscription_and_repeated_import(people):
    a, _ = people
    first = imported(a)
    second = imported(a)
    # Removing a duplicate import cannot remove the original subscription.
    assert client(a).delete(f'/api/me/rss-imports/{second}/').data['removed_count'] == 0
    assert ChannelSubscription.objects.filter(user=a).count() == 2
    original = ChannelSubscription.objects.filter(user=a).first()
    source = original.source
    unsubscribe(a, original.pk)
    replacement = ChannelSubscription.objects.create(user=a, source=source)
    result = client(a).delete(f'/api/me/rss-imports/{first}/')
    assert result.data['removed_count'] == 1
    assert ChannelSubscription.objects.filter(pk=replacement.pk).exists()


def test_old_batches_have_no_download_or_unproven_removal(people):
    a, _ = people
    batch = RssImportBatch.objects.create(user=a, file_hash='0' * 64, expires_at=timezone.now())
    assert client(a).get(f'/api/me/rss-imports/{batch.pk}/file/').status_code == 404
    assert client(a).delete(f'/api/me/rss-imports/{batch.pk}/').data['removed_count'] == 0


def test_removal_requires_session_csrf_and_full_mode(people, settings):
    a, _ = people
    identity = imported(a)
    path = f'/api/me/rss-imports/{identity}/'
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(a)
    assert session.delete(path).status_code == 403
    settings.PUBLIC_SITE_MODE = 'read_only'
    assert client(a).delete(path).status_code == 403
    assert ChannelSubscription.objects.filter(user=a).count() == 2


def test_removal_during_actual_control_worker_request_fences_late_commit(people, monkeypatch, lab):
    import time
    from threading import Event
    from api.tests.rss.test_control_worker import CONFIG, drain
    a, _ = people
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(CONFIG.engine_instance_uuid))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', str(CONFIG.account_id))
    result = preview(a, b'<opml><body><outline type="rss" xmlUrl="https://publisher.example/Feed"/></body></opml>')
    client(a).post('/api/me/rss-imports/confirm/', confirmation(result), format='json')
    process_imports()
    worker, engine = lab
    entered, release = Event(), Event()
    engine.create_hook = lambda: (entered.set(), release.wait(10))
    try:
        worker.tick()
        assert entered.wait(5)
        response = client(a).delete(f"/api/me/rss-imports/{result.data['id']}/")
        assert response.status_code == 200
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while worker.status()['control_busy'] and time.monotonic() < deadline:
        worker.tick()
        time.sleep(0.01)
    drain(worker)
    assert not ChannelSubscription.objects.filter(user=a).exists()
    operation = RssImportItem.objects.get(batch_id=result.data['id']).operation
    assert operation.state == 'cancelled'
    assert engine.create_calls == 1
    assert engine.feeds[7].disabled


def test_sensitive_upload_is_not_exposed_in_history_or_detail(people):
    a, b = people
    raw = b'<opml><body><outline text="private-label" xmlUrl="https://example.com/feed?token=synthetic-private-value"/></body></opml>'
    result = preview(a, raw)
    identity = result.data['id']
    for response in [result, client(a).get('/api/me/rss-imports/'), client(a).get(f'/api/me/rss-imports/{identity}/')]:
        assert 'synthetic-private-value' not in str(response.data)
        assert 'private-label' not in str(response.data)
    assert client(a).get(f'/api/me/rss-imports/{identity}/file/').content == raw
    assert client(b).get(f'/api/me/rss-imports/{identity}/file/').status_code == 404


def test_history_is_bounded_and_does_not_load_file_blobs(people):
    from datetime import timedelta
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    a, _ = people
    RssImportBatch.objects.bulk_create([RssImportBatch(user=a, file_hash=str(i).zfill(64),
        filename=f'{i}.opml', expires_at=timezone.now() + timedelta(minutes=30)) for i in range(21)])
    with CaptureQueriesContext(connection) as queries:
        first = client(a).get('/api/me/rss-imports/?page=1')
    assert first.data['count'] == 21 and len(first.data['results']) == 20
    assert first.data['has_next'] is True
    assert not any('"file_content"' in query['sql'] for query in queries.captured_queries)
    second = client(a).get('/api/me/rss-imports/?page=2')
    assert len(second.data['results']) == 1 and second.data['has_next'] is False
    assert not ({row['id'] for row in first.data['results']} & {row['id'] for row in second.data['results']})
