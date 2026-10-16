"""Stored readers recheck current grants after transient locks, fail closed after limits."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from django.db import OperationalError
from api.services import stored_readers as readers
from api.rss import operations


@pytest.mark.django_db(transaction=True)
def test_current_snapshot_retries_whole_read_without_returning_old_snapshot(monkeypatch):
    old = SimpleNamespace(news_id=1,scope='full',canonical_hash='old',revision=1,title='old',summary='old',provenance={})
    changed = SimpleNamespace(news_id=1,scope='summary',canonical_hash='new',revision=1,title='old',summary='old',provenance={})
    call=Mock(side_effect=[OperationalError('database table is locked'),changed])
    monkeypatch.setattr(readers,'get_stored_article',call)
    monkeypatch.setattr(operations.time,'sleep',lambda _:None)
    with pytest.raises(readers.StoredContentChanged): readers.require_current(None,old,full=True)
    assert call.call_count==2


@pytest.mark.django_db(transaction=True)
def test_current_snapshot_lock_exhaustion_is_safe_bounded_error(monkeypatch):
    call=Mock(side_effect=OperationalError('database table is locked: protected_table'))
    monkeypatch.setattr(readers,'get_stored_article',call)
    monkeypatch.setattr(operations.time,'sleep',lambda _:None)
    with pytest.raises(readers.StoredContentChanged,match='读取暂不可用') as error:
        readers.require_current(None,SimpleNamespace(news_id=1))
    assert call.call_count==20 and 'protected_table' not in str(error.value)


@pytest.mark.django_db
def test_quarantined_unchanged_hash_finishes_history_without_current_success():
    from django.utils import timezone
    from api.models import Category, News, Source, SharedArticleTranslation
    from api.services import shared_translations as shared
    source=Source.objects.create(name='quarantine fixture',url='https://example.test/')
    category=Category.objects.create(name='quarantine fixture',slug='quarantine-fixture')
    news=News.objects.create(source=source,category=category,title='old',content='summary',
        url='https://example.test/old',publish_time=timezone.now(),full_content='retained bytes',full_content_state='missing')
    digest=shared.source_hash(news.full_content)
    with pytest.raises(shared.SharedTranslationError,match='原文已更新'):
        shared.publish_translation(news_id=news.pk,digest=digest,text='历史译文',provider='synthetic')
    assert SharedArticleTranslation.objects.get(news=news,source_hash=digest).content=='历史译文'
    news.refresh_from_db()
    assert news.full_content_state=='missing' and not news.full_content_zh


def test_cached_complete_sse_lock_exhaustion_emits_safe_error(monkeypatch):
    from api.services import shared_translations as shared
    monkeypatch.setattr(shared,'require_current',Mock(side_effect=readers.StoredContentChanged('DB unavailable')))
    response=shared.completed_response(SimpleNamespace(content='must not leak'),stored=object())
    payload=b''.join(response.streaming_content).decode()
    assert 'error' in payload and 'must not leak' not in payload and 'DB unavailable' not in payload
