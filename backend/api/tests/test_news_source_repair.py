"""Explicit local repairs preserve IDs, histories and later CAS writes."""
from datetime import timedelta
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.utils import timezone

from api.models import (Category, ChatSession, ChatGPTArticleTranslation, ChatGPTSubscriptionConnection,
                        Favorite, News, NewsSourceItem, RequestBudget, SharedArticleTranslation, Source)
from api.services import news_source_repair as repair
from api.services.full_content_status import claim_fetch, mark_failed, mark_success, owns_fetch
from api.services.article_fetcher.types import FetchResult, FullContentCandidate
from api.services.shared_translations import cache_key, source_hash


pytestmark = pytest.mark.django_db


@pytest.fixture
def rows(monkeypatch):
    from api.services import article_fetcher
    monkeypatch.setattr(article_fetcher, 'fetch_article_markdown', Mock(side_effect=AssertionError('repair must never fetch')))
    source = Source.objects.create(name='量子位', url='https://www.leiphone.com', language='zh')
    category = Category.objects.create(name='Repair tests', slug='repair-tests')
    news = News.objects.create(
        source=source, category=category, title='Historical publisher title',
        content='Historical summary', content_zh='历史摘要',
        url='https://www.leiphone.com/category/ai/old-id.html', publish_time=timezone.now(),
        full_content='Historical original body', full_content_zh='历史完整译文',
        full_content_state='legacy', content_kind='article',
        suggested_questions=['An old cached question'], suggested_questions_generated_at=timezone.now(),
    )
    user = get_user_model().objects.create_user(username='repair-test-reader')
    favorite = Favorite.objects.create(user=user, news=news, type='bookmark')
    ChatSession.objects.create(user=user, news=news, messages=[{'role': 'user', 'content': 'Private historical conversation'}])
    connection = ChatGPTSubscriptionConnection.objects.create(
        user=user, subject_hash='repair-user', issuer='https://auth.example.test',
        issued_client_id='synthetic-client', registration_key_hash='synthetic-registration',
        encrypted_access_token='synthetic-access', encrypted_refresh_token='synthetic-refresh',
        selected_model='synthetic-model', is_active=True,
    )
    ChatGPTArticleTranslation.objects.create(user=user, connection=connection, news=news,
        source_hash=source_hash(news.full_content), model_slug='synthetic-model',
        content='Private historical translation', completed_at=timezone.now())
    translation = SharedArticleTranslation.objects.create(
        **cache_key(news.pk, source_hash(news.full_content)), content='历史共享译文',
        provider='chatgpt', completed_at=timezone.now(),
    )
    return source, news, favorite, translation


def evidence(kind='verified_article_url', **extra):
    return {'kind': kind, 'source_key': 'leiphone', 'reference': 'Local reviewed publisher evidence artifact #17', **extra}


def news_operation(news, *, new=None, equivalent=False):
    new = new or {'url': 'https://www.leiphone.com/category/ai/verified-id.html'}
    return {
        'action': 'repair_news_identity', 'news_id': news.pk,
        'expected': {'source_id': news.source_id, 'url': news.url, 'full_content_revision': news.full_content_revision},
        'new': new,
        'evidence': evidence('equivalent_article_url' if equivalent else 'verified_article_url',
                             verified_url=new.get('url', news.url), **({'body_sha256': source_hash(news.full_content)} if equivalent else {})),
    }


def rename_operation(source, news_ids):
    return {'action': 'rename_leiphone_source', 'source_id': source.pk,
            'expected': {'name': source.name, 'url': source.url}, 'news_ids': news_ids,
            'evidence': evidence('publisher_source_identity')}


def mapping_file(tmp_path, operations, name='mapping.json'):
    path = tmp_path / name
    path.write_text(json.dumps({'schema_version': 1, 'operations': operations}))
    return path


def command(**options):
    output = StringIO()
    call_command('repair_news_sources', stdout=output, **options)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def proper_source():
    return Source.objects.create(name='雷峰网', url='https://www.leiphone.com', language='zh')


def repaired_url(tmp_path, rows, *, equivalent=False):
    source, news, _, _ = rows
    target = proper_source()
    operation = news_operation(news, new={'source_id': target.pk, 'url': 'https://www.leiphone.com/category/ai/verified-id.html'}, equivalent=equivalent)
    mapping = mapping_file(tmp_path, [operation])
    audit = tmp_path / 'applied.json'
    result = command(mapping=str(mapping), apply=True, audit_output=str(audit))
    assert result[0]['outcome'] == 'applied'
    news.refresh_from_db()
    return mapping, audit, operation


def test_default_dry_run_outputs_old_new_evidence_and_changes_nothing(tmp_path, rows):
    source, news, favorite, translation = rows
    before = repair._news_snapshot(news)
    mapping = mapping_file(tmp_path, [rename_operation(source, [news.pk])])

    report = command(mapping=str(mapping))

    source.refresh_from_db()
    news.refresh_from_db()
    assert source.name == '量子位'
    assert repair._news_snapshot(news) == before
    assert report[0]['mode'] == 'dry-run'
    assert report[0]['source_id'] == source.pk
    assert report[0]['before']['name'] == '量子位'
    assert report[0]['after']['name'] == '雷峰网'
    assert report[0]['evidence']['reference']
    assert report[-1]['summary']['proposed'] == 1
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk
    assert SharedArticleTranslation.objects.get(pk=translation.pk).news_id == news.pk
    assert list(tmp_path.iterdir()) == [mapping]


def test_verified_source_rename_preserves_source_news_user_relationships_and_is_reversible(tmp_path, rows):
    source, news, favorite, translation = rows
    mapping = mapping_file(tmp_path, [rename_operation(source, [news.pk])])
    audit = tmp_path / 'rename.json'

    report = command(mapping=str(mapping), apply=True, audit_output=str(audit))

    source.refresh_from_db()
    news.refresh_from_db()
    assert report[0]['outcome'] == 'applied'
    assert source.name == '雷峰网'
    assert news.source_id == source.pk
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk
    assert SharedArticleTranslation.objects.get(pk=translation.pk).content == '历史共享译文'
    assert ChatSession.objects.get(news=news).messages == [{'role': 'user', 'content': 'Private historical conversation'}]
    assert ChatGPTArticleTranslation.objects.get(news=news).content == 'Private historical translation'
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    rerun = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'rerun.json'))
    assert rerun[0]['outcome'] == 'already_satisfied'
    preview = command(undo_audit=str(audit))
    assert preview[0]['outcome'] == 'proposed'
    assert Source.objects.get(pk=source.pk).name == '雷峰网'
    undone = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo.json'))
    assert undone[0]['outcome'] == 'undone'
    source.refresh_from_db()
    assert source.name == '量子位'
    assert command(undo_audit=str(audit))[0]['outcome'] == 'already_satisfied'


@pytest.mark.parametrize('conflict', ['target_exists', 'mixed_urls', 'mixed_mapping', 'incomplete_ids'])
def test_source_rename_refuses_ambiguous_scope_and_never_merges_or_deletes(tmp_path, rows, conflict):
    source, news, favorite, translation = rows
    if conflict == 'target_exists':
        proper_source()
    elif conflict == 'mixed_urls':
        News.objects.filter(pk=news.pk).update(url='https://webkit.org/blog/17/unrelated/')
    elif conflict == 'mixed_mapping':
        NewsSourceItem.objects.create(news=news, source_key='webkit', upstream_id='17', discovery_url=news.url)
    ids = [news.pk + 1] if conflict == 'incomplete_ids' else [news.pk]
    mapping = mapping_file(tmp_path, [rename_operation(source, ids)])

    result = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'conflict.json'))

    assert result[0]['outcome'] == 'conflict'
    assert Source.objects.get(pk=source.pk).name == '量子位'
    assert News.objects.filter(pk=news.pk).exists()
    assert Favorite.objects.filter(pk=favorite.pk, news_id=news.pk).exists()
    assert SharedArticleTranslation.objects.filter(pk=translation.pk).exists()


def test_explicit_fk_repair_moves_only_verified_news_and_preserves_old_source(tmp_path, rows):
    source, news, favorite, _ = rows
    other = News.objects.create(source=source, category=news.category, title='Mixed article', content='Other summary',
                                url='https://webkit.org/blog/18/other/', publish_time=timezone.now())
    target = proper_source()
    operation = news_operation(news, new={'source_id': target.pk})
    mapping = mapping_file(tmp_path, [operation])

    result = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'fk.json'))

    assert result[0]['outcome'] == 'applied'
    news.refresh_from_db()
    other.refresh_from_db()
    assert news.source_id == target.pk
    assert news.full_content_state == 'legacy'
    assert news.full_content == 'Historical original body'
    assert other.source_id == source.pk
    assert Source.objects.filter(pk=source.pk).exists()
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk


def test_url_conflict_preserves_both_rows_and_relationships(tmp_path, rows):
    source, news, favorite, _ = rows
    target = proper_source()
    occupied = News.objects.create(source=target, category=news.category, title='Another story', content='Other',
        url='https://www.leiphone.com/category/ai/verified-id.html', publish_time=timezone.now())
    mapping = mapping_file(tmp_path, [news_operation(news, new={'source_id': target.pk, 'url': occupied.url})])

    result = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'collision.json'))

    assert result[0]['outcome'] == 'conflict'
    assert result[0]['reason'] == 'target_url_exists_no_automatic_merge'
    news.refresh_from_db()
    assert news.source_id == source.pk
    assert News.objects.count() == 2
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk


def test_changed_identity_quarantines_history_queues_with_cooldown_and_fences_old_lease(tmp_path, rows):
    source, news, favorite, translation = rows
    News.objects.filter(pk=news.pk).update(full_content_fetch_status='queued', full_content_next_attempt_at=timezone.now())
    news.refresh_from_db()
    old_lease = claim_fetch(news)
    assert old_lease
    published = news.publish_time
    cooldown = timezone.now() + timedelta(minutes=10)
    RequestBudget.objects.create(key='host:www.leiphone.com', cooldown_until=cooldown)

    mapping, audit, operation = repaired_url(tmp_path, rows)

    assert news.full_content_revision == 1
    assert news.full_content_state == 'missing'
    assert news.full_content_fetch_status == 'queued'
    assert news.full_content_next_attempt_at >= cooldown
    assert news.last_full_content_attempt is None
    assert news.full_content == 'Historical original body'
    assert news.full_content_zh == '历史完整译文'
    assert news.publish_time == published
    assert news.suggested_questions == []
    stale = News.objects.get(pk=news.pk)
    stale._full_content_snapshot = old_lease
    assert not owns_fetch(stale)
    assert not mark_failed(stale, RuntimeError('late old executor failure'))
    stale._full_content_snapshot = old_lease
    candidate = FullContentCandidate('leiphone', old_lease.expected_url, old_lease.expected_url,
        'https://www.leiphone.com/feed', None, news.title, 'article', 'description', 'html', 'full',
        '<p>The complete old executor body.</p>', None, None, old_lease.claimed_at)
    assert not mark_success(stale, FetchResult(True, 'old_executor', candidate=candidate))
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk
    assert SharedArticleTranslation.objects.get(pk=translation.pk).content == '历史共享译文'
    saved = json.loads(audit.read_text())
    assert saved['operations'][0]['after']['body_sha256'] == source_hash(news.full_content)
    assert 'Historical original body' not in audit.read_text()
    assert '历史完整译文' not in audit.read_text()
    assert 'repair-test-reader' not in audit.read_text()
    assert 'Private historical conversation' not in audit.read_text()
    assert 'Private historical translation' not in audit.read_text()
    assert command(mapping=str(mapping))[0]['outcome'] == 'already_satisfied'


def test_equivalent_body_requires_digest_evidence_and_preserves_readability(tmp_path, rows):
    _, news, _, _ = rows
    _, audit, _ = repaired_url(tmp_path, rows, equivalent=True)
    assert news.full_content_state == 'legacy'
    assert news.full_content_revision == 1

    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undone.json'))

    assert result[0]['outcome'] == 'undone'
    news.refresh_from_db()
    assert news.url.endswith('/old-id.html')
    assert news.full_content_revision == 2
    assert news.full_content_state == 'legacy'
    assert news.suggested_questions == ['An old cached question']
    assert command(undo_audit=str(audit))[0]['outcome'] == 'already_satisfied'


def test_equivalence_cannot_preserve_body_without_matching_explicit_digest(tmp_path, rows):
    _, news, _, _ = rows
    target = proper_source()
    operation = news_operation(news, new={'source_id': target.pk, 'url': 'https://www.leiphone.com/category/ai/verified-id.html'}, equivalent=True)
    operation['evidence']['body_sha256'] = '0' * 64
    mapping = mapping_file(tmp_path, [operation])

    report = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'bad-equivalence.json'))

    assert report[0]['outcome'] == 'conflict'
    assert report[0]['reason'] == 'equivalent_body_digest_evidence_required'
    news.refresh_from_db()
    assert news.full_content_revision == 0
    assert news.url.endswith('/old-id.html')


def test_undo_url_collision_preserves_new_occupant_and_original_rows(tmp_path, rows):
    source, news, favorite, _ = rows
    _, audit, operation = repaired_url(tmp_path, rows)
    occupant = News.objects.create(source=source, category=news.category, title='Later valid occupant', content='Later summary',
        url=operation['expected']['url'], publish_time=timezone.now())

    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo-collision.json'))

    assert result[0]['outcome'] == 'conflict'
    assert result[0]['reason'] == 'undo_target_url_conflict'
    assert News.objects.get(pk=occupant.pk).url == operation['expected']['url']
    news.refresh_from_db()
    assert news.url.endswith('/verified-id.html')
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk
    assert News.objects.count() == 2


@pytest.mark.parametrize('change', ['url', 'source_id', 'revision', 'body', 'state', 'claim', 'translation'])
def test_undo_never_overwrites_changed_values_or_body_version(tmp_path, rows, change):
    _, news, _, _ = rows
    _, audit, _ = repaired_url(tmp_path, rows)
    updates = {
        'url': {'url': 'https://www.leiphone.com/category/ai/later-id.html'},
        'source_id': {'source_id': Source.objects.create(name='Later source', url='https://webkit.org').pk},
        'revision': {'full_content_revision': 2},
        'body': {'full_content': 'Later article body without old version evidence'},
        'state': {'full_content_state': 'complete'},
        'claim': {'full_content_fetch_status': 'fetching', 'last_full_content_attempt': timezone.now()},
        'translation': {'full_content_zh': '后来的译文'},
    }[change]
    News.objects.filter(pk=news.pk).update(**updates)
    news.refresh_from_db()
    current = repair._news_snapshot(news)

    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo-conflict.json'))

    assert result[0]['outcome'] == 'conflict'
    news.refresh_from_db()
    assert repair._news_snapshot(news) == current


def test_undo_checks_source_rename_news_body_versions(tmp_path, rows):
    source, news, _, _ = rows
    mapping = mapping_file(tmp_path, [rename_operation(source, [news.pk])])
    audit = tmp_path / 'rename.json'
    command(mapping=str(mapping), apply=True, audit_output=str(audit))
    News.objects.filter(pk=news.pk).update(full_content_revision=1)

    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo.json'))

    assert result[0]['outcome'] == 'conflict'
    assert Source.objects.get(pk=source.pk).name == '雷峰网'


@pytest.mark.parametrize('source_key,name,url', [('reuters', 'Reuters', 'https://www.reuters.com/site-search/?query=title'),
                                                ('jiqizhixin', '机器之心', 'https://www.jiqizhixin.com/articles/guessed-title')])
def test_explicit_unverified_record_keeps_metadata_but_disables_body_and_never_guesses_url(tmp_path, rows, source_key, name, url):
    _, news, favorite, _ = rows
    source = Source.objects.create(name=name, url='https://' + ('www.reuters.com' if source_key == 'reuters' else 'www.jiqizhixin.com'))
    News.objects.filter(pk=news.pk).update(source=source, url=url)
    news.refresh_from_db()
    operation = {'action': 'quarantine_unverified_identity', 'news_id': news.pk,
                 'expected': {'source_id': source.pk, 'url': url, 'full_content_revision': 0},
                 'evidence': {'kind': 'unverified_identity', 'source_key': source_key, 'reference': 'Reviewed missing publisher identity evidence'}}
    mapping = mapping_file(tmp_path, [operation])

    result = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'quarantine.json'))

    news.refresh_from_db()
    assert result[0]['outcome'] == 'applied'
    assert news.url == url
    assert news.full_content_state == 'missing'
    assert news.full_content_fetch_status == 'unsupported'
    assert news.full_content_error_code == 'invalid_identity'
    assert news.full_content_next_attempt_at is None
    assert news.full_content == 'Historical original body'
    assert news.content == 'Historical summary'
    assert Favorite.objects.get(pk=favorite.pk).news_id == news.pk


def test_invalid_mapping_missing_evidence_and_existing_audit_never_write(tmp_path, rows):
    source, news, _, _ = rows
    operation = rename_operation(source, [news.pk])
    mapping = mapping_file(tmp_path, [operation])
    with pytest.raises(CommandError, match='apply_requires'):
        command(mapping=str(mapping), apply=True)
    existing = tmp_path / 'existing.json'
    existing.write_text('existing protected audit')
    with pytest.raises(CommandError, match='already_exists'):
        command(mapping=str(mapping), apply=True, audit_output=str(existing))
    operation['evidence']['reference'] = ''
    mapping_file(tmp_path, [operation])
    with pytest.raises(CommandError, match='evidence_reference'):
        command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'invalid.json'))
    assert Source.objects.get(pk=source.pk).name == '量子位'
    assert existing.read_text() == 'existing protected audit'


def test_prepared_audit_can_undo_commit_even_if_final_audit_write_failed(tmp_path, rows, monkeypatch):
    _, news, _, _ = rows
    target = proper_source()
    mapping = mapping_file(tmp_path, [news_operation(news, new={'source_id': target.pk, 'url': 'https://www.leiphone.com/category/ai/verified-id.html'})])
    audit = tmp_path / 'prepared.json'
    from api.management.commands import repair_news_sources as command_module
    real_write = repair.write_audit
    calls = 0

    def failing_write(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise repair.RepairInputError('audit_write_failed')
        return real_write(*args, **kwargs)

    monkeypatch.setattr(command_module, 'write_audit', failing_write)
    with pytest.raises(CommandError, match='audit_write_failed'):
        command(mapping=str(mapping), apply=True, audit_output=str(audit))
    assert json.loads(audit.read_text())['operations'][0]['outcome'] == 'prepared'
    news.refresh_from_db()
    assert news.full_content_revision == 1
    monkeypatch.setattr(command_module, 'write_audit', real_write)

    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo-prepared.json'))

    assert result[0]['outcome'] == 'undone'
    news.refresh_from_db()
    assert news.full_content_revision == 2
    assert news.url.endswith('/old-id.html')


def test_late_cooldown_or_target_source_change_conflicts_before_apply(tmp_path, rows):
    _, news, _, _ = rows
    target = proper_source()
    operation = news_operation(news, new={'source_id': target.pk, 'url': 'https://www.leiphone.com/category/ai/verified-id.html'})
    plan = repair.plan_operation(operation)
    RequestBudget.objects.create(key='host:www.leiphone.com', cooldown_until=timezone.now() + timedelta(days=1))
    result = repair.apply_plan(plan)
    assert result['outcome'] == 'conflict'
    assert result['reason'] == 'persistent_cooldown_changed_review_again'
    assert News.objects.get(pk=news.pk).full_content_revision == 0
    plan = repair.plan_operation(operation)
    Source.objects.filter(pk=target.pk).update(url='https://unrelated.example.test')
    assert repair.apply_plan(plan)['outcome'] == 'conflict'
    assert News.objects.get(pk=news.pk).full_content_revision == 0


def test_real_file_wal_command_dry_run_apply_and_undo(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = r'''
import django, json, os, socket
from io import StringIO
from pathlib import Path
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('repair cannot fetch'))
django.setup()
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from api.models import News, Source, Category
call_command('migrate', verbosity=0)
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode')
    assert cursor.fetchone()[0] == 'wal'
source = Source.objects.create(name='量子位', url='https://www.leiphone.com')
news = News.objects.create(title='Explicit old article', content='Summary', source=source,
    category=Category.objects.create(name='Temporary repair', slug='temporary-repair'),
    url='https://www.leiphone.com/category/ai/old-id.html', publish_time=timezone.now(),
    full_content='Preserved historical body', full_content_state='legacy')
work = Path(os.environ['TEST_REPAIR_ROOT'])
mapping = work / 'mapping.json'
mapping.write_text(json.dumps({'schema_version':1, 'operations':[{
    'action':'rename_leiphone_source','source_id':source.pk,
    'expected':{'name':source.name,'url':source.url},'news_ids':[news.pk],
    'evidence':{'kind':'publisher_source_identity','source_key':'leiphone','reference':'Local publisher evidence'}
}]}))
call_command('repair_news_sources', mapping=str(mapping), stdout=StringIO())
source.refresh_from_db()
assert source.name == '量子位'
audit = work / 'apply.json'
call_command('repair_news_sources', mapping=str(mapping), apply=True, audit_output=str(audit), stdout=StringIO())
source.refresh_from_db()
assert source.name == '雷峰网'
call_command('repair_news_sources', undo_audit=str(audit), apply=True, audit_output=str(work/'undo.json'), stdout=StringIO())
source.refresh_from_db()
news.refresh_from_db()
assert source.name == '量子位' and news.source_id == source.pk and news.full_content == 'Preserved historical body'
print(json.dumps({'wal':True,'dry_run':True,'apply':True,'undo':True}))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env={
        **os.environ, 'PYTHONPATH': str(root / 'backend'), 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'RUN_MAIN': 'true', 'DJANGO_ENV': 'development', 'DJANGO_DB_PATH': str(tmp_path / 'repair.sqlite3'),
        'TEST_REPAIR_ROOT': str(tmp_path),
    }, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {'wal': True, 'dry_run': True, 'apply': True, 'undo': True}



def test_reviewed_new_url_starts_audited_identity_cycle_but_keeps_host_cooldown(tmp_path, rows):
    _source, news, _favorite, _translation = rows
    News.objects.filter(pk=news.pk).update(full_content_retry_count=5, full_content_fetch_status='failed')
    news.refresh_from_db()
    deadline = timezone.now() + timedelta(hours=1)
    RequestBudget.objects.create(key='host:leiphone.com', cooldown_until=deadline)
    # www aliases use the exact host scope; cover the current URL's real key.
    from api.services.request_budget import scope_intervals
    for key in scope_intervals(news.url):
        RequestBudget.objects.update_or_create(key=key, defaults={'cooldown_until': deadline})
    _mapping, audit, _operation = repaired_url(tmp_path, rows)
    assert news.full_content_retry_count == 0 and news.full_content_task_created_at is not None
    assert news.full_content_next_attempt_at >= deadline and not claim_fetch(news)
    result = command(undo_audit=str(audit), apply=True, audit_output=str(tmp_path / 'undo-cycle.json'))
    assert result[0]['outcome'] == 'undone'
    news.refresh_from_db()
    assert news.full_content_retry_count == 5 and news.full_content_task_created_at is None


def test_source_fk_only_repair_keeps_exhaustion_and_has_no_unrunnable_queue(tmp_path, rows):
    _source, news, _favorite, _translation = rows
    News.objects.filter(pk=news.pk).update(full_content_retry_count=5, full_content_fetch_status='failed')
    news.refresh_from_db()
    mapping = mapping_file(tmp_path, [news_operation(news, new={'source_id': proper_source().pk})])
    result = command(mapping=str(mapping), apply=True, audit_output=str(tmp_path / 'source-only.json'))
    assert result[0]['outcome'] == 'applied'
    news.refresh_from_db()
    assert news.full_content_retry_count == 5 and news.full_content_next_attempt_at is None
    assert news.full_content_error_code == 'retry_exhausted' and news.full_content_state == 'legacy'


def test_later_failure_counter_update_is_also_an_undo_fence(tmp_path, rows):
    _mapping, audit, _operation = repaired_url(tmp_path, rows)
    news = rows[1]
    News.objects.filter(pk=news.pk).update(full_content_retry_count=1)
    result = command(undo_audit=str(audit))
    assert result[0]['outcome'] == 'conflict'
