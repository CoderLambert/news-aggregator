"""Repair orchestration reuses durable intents; no engine requests in the CLI."""
import pytest
from django.core.management import call_command
from api.rss.body_repair import preview, submit, outcome
from api.rss.models import FeedOperation
from api.rss.operations import OperationError
from api.tests.rss.test_control_worker import setup_article, FakeEngine

pytestmark = pytest.mark.django_db(transaction=True)


def row(settings):
    settings.RSS_FULL_CONTENT_ENABLED = True
    *_, news, entry = setup_article(FakeEngine())
    return news, entry, preview()['rows'][0]


def test_preview_is_read_only_and_repeat_submit_never_reissues_unknown(settings):
    news, entry, candidate = row(settings)
    assert candidate['status'] == 'candidate'
    assert not FeedOperation.objects.exists()
    first = submit(candidate)
    FeedOperation.objects.filter(pk=first.pk).update(state='unknown', safe_result={'outcome_unknown': True})
    again = submit(candidate)
    assert again.pk == first.pk
    assert outcome(again) == 'unconfirmed'
    again.state = 'cancelled'
    assert outcome(again) == 'unconfirmed'
    assert FeedOperation.objects.count() == 1
    news.refresh_from_db()
    assert news.full_content == 'old body'


def test_stale_preview_does_not_enqueue(settings):
    news, entry, candidate = row(settings)
    news.full_content_revision += 1
    news.save(update_fields=['full_content_revision'])
    with pytest.raises(OperationError, match='preview_stale'):
        submit(candidate)
    assert not FeedOperation.objects.exists()


def test_summary_policy_is_skipped(settings):
    news, entry, candidate = row(settings)
    publication = news.source.publication
    publication.reading_policy = 'rss_summary_only'
    publication.save()
    assert preview()['rows'][0]['status'] == 'skipped'


def test_success_requires_sync_ack(settings):
    _, _, candidate = row(settings)
    op = submit(candidate)
    op.state = 'succeeded'
    op.safe_result = {'pending_sync': True}
    assert outcome(op) == 'waiting'
    op.safe_result = {'pending_sync': False, 'sync_status': 'stale'}
    assert outcome(op) == 'failed'
    op.safe_result['sync_status'] = 'accepted'
    assert outcome(op) == 'success'


def test_command_preview_and_resume_preserve_manifest(settings, tmp_path):
    import json
    _, _, candidate = row(settings)
    path = tmp_path / 'manifest.json'
    call_command('rss_repair_bodies', 'preview', manifest=str(path))
    assert not FeedOperation.objects.exists()
    op = submit(candidate)
    FeedOperation.objects.filter(pk=op.pk).update(state='succeeded', safe_result={'sync_status': 'unchanged'})
    call_command('rss_repair_bodies', 'execute', manifest=str(path))
    call_command('rss_repair_bodies', 'resume', manifest=str(path))
    assert json.loads(path.read_text())['rows'][0]['status'] == 'success'
    assert FeedOperation.objects.count() == 1


def test_policy_opt_in_is_explicit_and_restore_keeps_body(settings, tmp_path):
    import json
    news, entry, _ = row(settings)
    binding = entry.binding
    binding.desired_mode = 'feed'
    binding.save()
    ambiguous = tmp_path / 'ambiguous.json'
    call_command('rss_repair_policy', 'preview', manifest=str(ambiguous))
    assert json.loads(ambiguous.read_text())['rows'][0]['reason'] == 'mode_origin_unconfirmed'
    path = tmp_path / 'policy.json'
    call_command('rss_repair_policy', 'preview', manifest=str(path), target_feed=binding.canonical_feed_url)
    call_command('rss_repair_policy', 'execute', manifest=str(path))
    call_command('rss_repair_policy', 'execute', manifest=str(path))
    binding.refresh_from_db()
    assert binding.desired_mode == 'full_content'
    assert binding.policy_version == 2
    call_command('rss_repair_policy', 'restore', manifest=str(path))
    binding.refresh_from_db()
    news.refresh_from_db()
    assert binding.desired_mode == 'feed'
    assert binding.policy_version == 3
    assert news.full_content == 'old body'
