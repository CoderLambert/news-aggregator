"""Current per-user SQL and stored-body ACL with isolated synthetic data."""
import uuid
from dataclasses import replace

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.http import Http404
from django.utils import timezone

from api.models import Category, ChannelSubscription, Favorite, News, Source
from api.rss.models import EngineEntryMap, FeedBinding, SourceFeedLink, SourcePublication
from api.rss.access import authorized_news, authorized_sources, body_authorized_news, get_stored_article

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    a, b = User.objects.create_user('acl-a'), User.objects.create_user('acl-b')
    category = Category.objects.create(name='ACL', slug='acl')

    def make(name, publication='personal', subscriber=None, policy='standard', owner='legacy', state='legacy'):
        source = Source.objects.create(name=name, url=f'https://{name}.example/')
        SourcePublication.objects.create(source=source, publication=publication, owner=owner, reading_policy=policy)
        if subscriber:
            ChannelSubscription.objects.create(user=subscriber, source=source)
        news = News.objects.create(source=source, category=category, title=name, content='summary ' + name,
            url=f'https://article.example/{name}', publish_time=timezone.now(),
            full_content='private body ' + name, full_content_state=state, body_owner_source=source)
        return source, news
    return a, b, make


def test_sql_acl_a_b_anonymous_paused_missing_publication(world):
    a, b, make = world
    public, pn = make('public', 'public', owner='paused')
    personal, an = make('personal', subscriber=a, owner='paused')
    _, bn = make('other', subscriber=b)
    missing, mn = make('missing', 'public')
    SourcePublication.objects.filter(source=missing).delete()
    assert set(authorized_news(a).values_list('pk', flat=True)) == {pn.pk, an.pk}
    assert set(authorized_news(b).values_list('pk', flat=True)) == {pn.pk, bn.pk}
    assert list(authorized_news(AnonymousUser()).values_list('pk', flat=True)) == [pn.pk]
    for user, hidden in [(b, an), (AnonymousUser(), an), (a, mn)]:
        with pytest.raises(Http404):
            get_stored_article(user, hidden.pk)
    assert get_stored_article(a, an.pk).scope == 'full'


@pytest.mark.parametrize('state', ['legacy', 'complete', 'available'])
def test_current_policy_and_subscription_no_cached_grant(world, state):
    a, _, make = world
    source, news = make('state' + state, subscriber=a, state=state)
    assert get_stored_article(a, news.pk).scope == 'full'
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only', policy_version=2)
    article = get_stored_article(a, news.pk)
    assert article.scope == 'summary' and article.markdown == news.content
    assert article.provenance == {} and article.body_owner is None
    assert not body_authorized_news(a).filter(pk=news.pk).exists()
    SourcePublication.objects.filter(source=source).update(reading_policy='unknown-policy')
    assert get_stored_article(a, news.pk).scope == 'summary'
    ChannelSubscription.objects.filter(user=a, source=source).delete()
    with pytest.raises(Http404):
        get_stored_article(a, news.pk)


def test_same_url_association_does_not_grant_other_binding_body(world):
    a, b, make = world
    private, news = make('private', subscriber=a)
    public, _ = make('associated', 'public')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        engine_feed_id=7, canonical_feed_url='https://feed.example/a')
    SourceFeedLink.objects.create(source=public, binding=binding, enabled=False)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=12, news=news,
        source_url=news.url, disposition='linked')
    assert authorized_news(b).filter(pk=news.pk).exists()
    assert get_stored_article(b, news.pk).scope == 'summary'
    assert get_stored_article(a, news.pk).scope == 'full'
    Favorite.objects.create(user=b, news=news, type='bookmark')
    SourceFeedLink.objects.filter(source=public).update(association_policy={'version': 999, 'mode': 'all'})
    with pytest.raises(Http404):
        get_stored_article(b, news.pk)


def test_engine_provenance_identity_and_current_origin_policy(world):
    a, b, make = world
    source, news = make('engine', subscriber=a, owner='paused', state='available')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        engine_feed_id=7, canonical_feed_url='https://feed.example/e')
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=False)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=12, news=news,
        source_url=news.url, disposition='linked')
    news.body_owner_source = None
    news.body_owner_binding = binding
    news.full_content_provenance = dict(owner='miniflux', binding_id=str(binding.pk),
        source_id=source.pk, engine_instance_uuid=str(binding.engine_instance_uuid),
        account_id=3, engine_feed_id=7, engine_entry_id=12)
    news.save()
    assert get_stored_article(a, news.pk).scope == 'full'
    assert get_stored_article(a, news.pk).body_owner == 'miniflux'
    with pytest.raises(Http404):
        get_stored_article(b, news.pk)
    news.full_content_provenance['account_id'] = 4
    news.save(update_fields=['full_content_provenance'])
    assert get_stored_article(a, news.pk).scope == 'summary'
    news.full_content_provenance['account_id'] = 3
    news.save(update_fields=['full_content_provenance'])
    SourcePublication.objects.filter(source=source).update(reading_policy='rss_summary_only')
    assert get_stored_article(a, news.pk).scope == 'summary'
