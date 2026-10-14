from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import json
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from api.models import Source, Category, News, ChannelSubscription
from api.services.channel_topics import evidence_for
from api.services.channel_evidence import evidence_is_current
from api.services.channel_grouping import make_proposal, apply_proposal, GroupingConflict
from api.services.channel_ai import claim_next, execute_job


@pytest.fixture
def setup_evidence(db, settings):
    settings.PUBLIC_SITE_MODE = 'full'; settings.PUBLIC_AI_ENABLED = True
    user = get_user_model().objects.create_user('evidence-reader')
    source, _ = Source.objects.get_or_create(name='React Blog', defaults={'url': 'https://react.dev'})
    category, _ = Category.objects.get_or_create(name='evidence', defaults={'slug': 'evidence'})
    article = News.objects.create(source=source, category=category, title='Original title',
        url='https://react.dev/blog/evidence-test', content='summary', publish_time=timezone.now())
    ChannelSubscription.objects.create(user=user, source=source)
    return user, source, article


def proposal(user, source):
    with patch('api.services.channel_grouping.credential_fingerprint', return_value='fixture-only'):
        return make_proposal(user, {'engine': 'ai', 'consent': True, 'source_ids': [source.pk], 'topic_keys': ['frontend']})


def test_title_change_invalidates_evidence_before_provider_io(setup_evidence):
    user, source, article = setup_evidence
    job = proposal(user, source)
    article.title = 'Corrected publisher title'; article.save(update_fields=['title'])
    claimed = claim_next(); assert claimed.pk == job.pk
    with patch('api.services.channel_ai.permitted', return_value=True), patch('api.services.channel_ai.personal_clients_for_user') as provider:
        execute_job(claimed)
    provider.assert_not_called()
    job.refresh_from_db()
    assert job.status == 'failed' and job.error_code == 'evidence_changed'


def test_title_change_during_model_call_cannot_commit_stale_result(setup_evidence):
    user, source, article = setup_evidence
    job = proposal(user, source)
    def create(**kwargs):
        News.objects.filter(pk=article.pk).update(title='Newly corrected title')
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content=json.dumps({'channels': [{'source_id': source.pk, 'topic_keys': ['frontend'], 'reason': 'fixture'}]})))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    with patch('api.services.channel_ai.permitted', return_value=True), patch('api.services.channel_ai.personal_clients_for_user', return_value=[(fake, 'fake-model')]):
        execute_job(claim_next())
    job.refresh_from_db()
    assert job.status == 'failed' and job.error_code == 'evidence_changed'
    assert job.result == [] or job.result[0].get('origin') != 'ai'


def test_ready_ai_preview_rechecks_titles_before_apply(setup_evidence):
    user, source, article = setup_evidence
    job = proposal(user, source)
    job.status = 'ready'; job.save(update_fields=['status'])
    before = evidence_for(source)
    assert evidence_is_current([before])
    News.objects.filter(pk=article.pk).update(title='Title changed after preview')
    assert not evidence_is_current([before])
    with pytest.raises(GroupingConflict):
        apply_proposal(user, job.pk, {'groups': [{'topic_key': 'frontend', 'source_ids': [source.pk], 'name': 'Frontend'}]})
    job.refresh_from_db(); assert job.status == 'ready'


def test_tied_publication_times_have_stable_evidence_order(setup_evidence):
    _, source, article = setup_evidence
    News.objects.create(source=source, category=article.category, title='Second title',
        url='https://react.dev/blog/evidence-second', content='summary', publish_time=article.publish_time)
    first, second = evidence_for(source), evidence_for(source)
    assert first == second and first['titles'][0] == 'Second title'
    assert 'titles_hash' in first and first['version'] == 'channel-evidence-2'
