import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from api.models import Source, Category, News, ChannelSubscription
from api.smart_channel_models import ChannelGroupingProposal, ChannelClassifierSettings, SourceTopicProfile
from api.services.channel_ai import execute_job
from api.services.channel_topics import evidence_for, base_profile
from api.services.channel_grouping import snapshot, apply_proposal, GroupingConflict
from api.services.classification_evidence import evidence_is_current


@pytest.fixture
def example(db):
    user = get_user_model().objects.create_superuser('evidence-admin', 'evidence@example.test', 'test-only')
    source = Source.objects.create(name='Evidence Source', url='https://example.test')
    category = Category.objects.create(name='evidence category', slug='evidence-category')
    article = News.objects.create(source=source, category=category, title='Original AI article',
        content='summary', url='https://example.test/article', publish_time=timezone.now())
    ChannelSubscription.objects.create(user=user, source=source)
    ChannelClassifierSettings.objects.create(pk=1, owner=user, enabled=True)
    return user, source, article


def job_for(example, public=True):
    user, source, _ = example
    return ChannelGroupingProposal.objects.create(user=user, public_source=source if public else None,
        source_ids=[source.pk], topic_keys=['ai'], engine='ai', status='running', attempts=1,
        lease_token='lease', lease_until=timezone.now() + timedelta(minutes=2),
        credential_fingerprint='fixture', input_snapshot=base_profile(source)['evidence_hash'] if public else snapshot(user, [source.pk]),
        evidence=[evidence_for(source)], expires_at=timezone.now() + timedelta(hours=1))


@pytest.mark.parametrize('public', [False, True])
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_changed_title_before_inference_rejects_without_model_call(example, public):
    job = job_for(example, public)
    News.objects.filter(pk=example[2].pk).update(title='A new title')
    with patch('api.services.channel_ai.credential_fingerprint', return_value='fixture'), \
         patch('api.services.channel_ai.personal_clients_for_user') as clients:
        execute_job(job)
    job.refresh_from_db()
    assert job.status == 'failed' and job.error_code == 'metadata_changed'
    clients.assert_not_called()


@pytest.mark.parametrize('public', [False, True])
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_changed_title_during_inference_cannot_commit_stale_classification(example, public):
    job = job_for(example, public)
    client = Mock()
    def completion(**kwargs):
        News.objects.filter(pk=example[2].pk).update(title='Changed while model ran')
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps({
            'channels': [{'source_id': example[1].pk, 'topic_keys': ['ai'], 'reason': 'fixture'}]})))])
    client.chat.completions.create.side_effect = completion
    with patch('api.services.channel_ai.credential_fingerprint', return_value='fixture'), \
         patch('api.services.channel_ai.personal_clients_for_user', return_value=[(client, 'fake')]):
        execute_job(job)
    job.refresh_from_db()
    assert job.status == 'failed' and job.error_code == 'metadata_changed'
    assert not SourceTopicProfile.objects.filter(source=example[1], origin='ai').exists()
    assert client.chat.completions.create.call_count == 1


def test_ready_ai_proposal_revalidates_titles_before_user_applies(example):
    job = job_for(example, public=False)
    job.status = 'ready'
    job.save(update_fields=['status'])
    assert evidence_is_current(job)
    News.objects.filter(pk=example[2].pk).update(title='Changed after preview became ready')
    with pytest.raises(GroupingConflict):
        apply_proposal(example[0], job.pk, {'groups': [{'topic_key': 'ai', 'source_ids': [example[1].pk]}]})
    job.refresh_from_db()
    assert job.status == 'ready' and job.applied_changes == []
