"""Current per-user SQL and stored-body ACL with isolated synthetic data."""
import uuid

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


def test_engine_body_origin_requires_current_entry_url_binding(world):
    from api.services.article_identity import normalize_article_url

    a, _, make = world
    source, news = make('engine-url', subscriber=a, owner='paused', state='available')
    normalized_url = normalize_article_url(
        'HTTPS://Article.Example/engine-url?utm_source=feed&story=7#body')
    assert normalized_url == 'https://article.example/engine-url?story=7'
    news.url = normalized_url
    news.save(update_fields=['url'])

    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        engine_feed_id=7, canonical_feed_url='https://feed.example/e')
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=False)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=12, news=news,
        source_url=normalized_url, disposition='linked')
    news.body_owner_source = None
    news.body_owner_binding = binding
    news.full_content_provenance = dict(owner='miniflux', binding_id=str(binding.pk),
        source_id=source.pk, engine_instance_uuid=str(binding.engine_instance_uuid),
        account_id=3, engine_feed_id=7, engine_entry_id=12)
    news.save(update_fields=['body_owner_source', 'body_owner_binding', 'full_content_provenance'])

    accepted = get_stored_article(a, news.pk)
    assert accepted.scope == 'full'
    assert accepted.url == normalized_url
    assert accepted.markdown == news.full_content

    # Simulate a stale/out-of-band News identity update while accepted bytes and
    # the Miniflux mapping still refer to the prior normalized article URL.
    news.url = 'https://article.example/engine-url?story=8'
    news.save(update_fields=['url'])
    assert not body_authorized_news(a).filter(pk=news.pk).exists()
    summary = get_stored_article(a, news.pk)
    assert summary.scope == 'summary'
    assert summary.markdown == news.content
    assert summary.provenance == {}
    assert summary.body_owner is None


def api_client(user=None):
    from rest_framework.test import APIClient
    client = APIClient()
    if user:
        client.force_authenticate(user)
    return client


def results(response):
    return response.data['results'] if isinstance(response.data, dict) and 'results' in response.data else response.data


def test_http_id_list_favorites_counts_and_dynamic_revocation(world, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    a, b, make = world
    public, pn = make('public', 'public', state='available')
    private, an = make('private', subscriber=a, state='complete')
    Favorite.objects.create(user=b, news=an, type='bookmark')  # historical relation is not permission
    Favorite.objects.create(user=a, news=an, type='like')
    for user, expected in [(None, {pn.pk}), (b, {pn.pk}), (a, {pn.pk, an.pk})]:
        client = api_client(user)
        response = client.get('/api/news/')
        assert response.status_code == 200
        assert {row['id'] for row in results(response)} == expected
        assert response['Cache-Control'] == 'private, no-store'
        detail = client.get(f'/api/news/{an.pk}/')
        assert detail.status_code == (200 if user == a else 404)
        sources = results(client.get('/api/sources/'))
        assert ({row['id'] for row in sources} & {public.pk, private.pk}) == ({public.pk, private.pk} if user == a else {public.pk})
        assert sum(row['news_count'] for row in sources) == len(expected)
        categories = results(client.get('/api/categories/'))
        assert sum(row['news_count'] for row in categories) == len(expected)
    client = api_client(b)
    assert results(client.get('/api/favorites/')) == []
    assert client.get('/api/favorites/check/', {'news_id': an.pk}).status_code == 404
    assert client.post('/api/favorites/', {'news_id': an.pk, 'type': 'bookmark'}).status_code == 404
    assert Favorite.objects.filter(user=b, news=an).exists()  # forbidden toggle doesn't remove history
    client = api_client(a)
    assert client.get(f'/api/news/{an.pk}/').data['full_content'] == an.full_content
    SourcePublication.objects.filter(source=private).update(reading_policy='summary_only', policy_version=2)
    detail = client.get(f'/api/news/{an.pk}/')
    assert detail.data['full_content'] == '' and not detail.data['has_full_content']
    assert detail.data['body_owner'] is None
    ChannelSubscription.objects.filter(user=a, source=private).delete()
    assert client.get(f'/api/news/{an.pk}/').status_code == 404
    assert results(client.get('/api/favorites/')) == []


def test_serialized_cross_feed_member_hides_private_primary_source_and_body(world):
    _, b, make = world
    source, news = make('secret-primary')
    public, _ = make('public-channel', 'public')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        canonical_feed_url='https://feed.example/public')
    SourceFeedLink.objects.create(source=public, binding=binding)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=9, news=news, source_url=news.url, disposition='linked')
    client = api_client(b)
    detail = client.get(f'/api/news/{news.pk}/')
    assert detail.status_code == 200
    assert detail.data['source'] == public.pk and detail.data['channel_ids'] == [public.pk]
    assert 'secret-primary' not in detail.data['source_name']
    assert detail.data['full_content'] == '' and not detail.data['has_full_content']
    Favorite.objects.create(user=b, news=news, type='bookmark')
    assert results(client.get('/api/favorites/'))[0]['news']['source_name'] == public.name


def test_semantic_candidate_reauthorization_and_summary_keyword(world, monkeypatch):
    import sys
    from types import SimpleNamespace
    a, b, make = world
    _, public = make('public', 'public')
    _, private = make('private', subscriber=a)
    monkeypatch.setattr('api.services.search_index_control.index_version_is_current', lambda: True)
    # Heavy vector/embedding models are not imported: only candidate IDs are under test.
    class Vector:
        def count(self):
            return 2
        def search(self, *args, **kwargs):
            return [(private.pk, .99), (public.pk, .8)]
    monkeypatch.setitem(sys.modules, 'api.services.vector_store', SimpleNamespace(VectorStoreService=Vector))
    monkeypatch.setitem(sys.modules, 'api.services.embedding', SimpleNamespace(EmbeddingService=SimpleNamespace(is_loaded=lambda: True)))
    client = api_client(b)
    for mode in ['semantic', 'hybrid', 'keyword']:
        response = client.get('/api/news/', {'search': 'summary', 'mode': mode})
        assert response.status_code == 200
        assert response.data['count'] == 1
        assert [row['id'] for row in response.data['results']] == [public.pk]


def test_full_body_search_filters_origin_permission_before_matching(world, monkeypatch):
    a, b, make = world
    _, private = make('private', subscriber=a)
    public, public_news = make('public', 'public')
    public_news.full_content = 'publicly readable article'
    public_news.save(update_fields=['full_content'])
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        canonical_feed_url='https://feed.example/public')
    SourceFeedLink.objects.create(source=public, binding=binding)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=9, news=private, source_url=private.url, disposition='linked')
    monkeypatch.setattr('api.services.account_security._reserve_buckets', lambda *args: None)
    response = api_client(b).get('/api/news/', {'search': 'body private', 'search_in': 'full'})
    assert response.status_code == 200
    assert response.data['count'] == 0
    response = api_client(a).get('/api/news/', {'search': 'private body private', 'search_in': 'full'})
    assert response.status_code == 200
    assert [row['id'] for row in response.data['results']] == [private.pk]


def test_catalog_dashboard_reading_stats_and_subscribe_cannot_grant_private_source(world, settings):
    from api.smart_channel_models import ReadingDay
    settings.PUBLIC_SITE_MODE = 'full'
    a, b, make = world
    public, pn = make('public', 'public')
    private, an = make('secret-private', subscriber=a)
    ReadingDay.objects.create(user=b, news=an, day=timezone.localdate())
    ReadingDay.objects.create(user=a, news=an, day=timezone.localdate())
    client = api_client(b)
    catalog = client.get('/api/smart-channels/catalog/')
    assert catalog.status_code == 200
    assert private.pk not in [row['id'] for row in catalog.data['sources']]
    assert client.get(f'/api/smart-channels/sources/{private.pk}/').status_code == 404
    dashboard = client.get('/api/smart-channels/dashboard/')
    assert dashboard.status_code == 200
    assert [row['id'] for row in dashboard.data['stories']] == [pn.pk]
    stats = client.get('/api/me/reading-stats/')
    assert stats.status_code == 200 and stats.data['total'] == 0
    assert client.post('/api/me/reading-stats/', {'news_id': an.pk}, format='json').status_code == 404
    response = client.post('/api/me/channel-subscriptions/', {'source_ids': [private.pk], 'action': 'subscribe'}, format='json')
    assert response.status_code == 404
    assert not ChannelSubscription.objects.filter(user=b, source=private).exists()


def test_inactive_user_and_privileged_permission_do_not_bypass_dynamic_policy(world):
    from django.contrib.auth.models import Permission
    a, _, make = world
    source, news = make('private', subscriber=a)
    a.user_permissions.add(Permission.objects.get(codename='view_article_body'))
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    assert get_stored_article(a, news.pk).scope == 'summary'
    a.is_active = False
    a.save(update_fields=['is_active'])
    with pytest.raises(Http404):
        get_stored_article(a, news.pk)


def test_empty_or_missing_body_owner_fails_closed(world):
    a, _, make = world
    _, news = make('body', subscriber=a)
    news.body_owner_source = None
    news.save(update_fields=['body_owner_source'])
    assert get_stored_article(a, news.pk).scope == 'summary'
    news.body_owner_source_id = news.source_id
    news.full_content = '  '
    news.save(update_fields=['body_owner_source', 'full_content'])
    assert get_stored_article(a, news.pk).scope == 'summary'


def test_body_derived_question_cache_not_exposed_after_policy_restriction(world, monkeypatch):
    a, _, make = world
    source, news = make('private', subscriber=a)
    news.suggested_questions = ['secret from body one', 'secret from body two', 'secret from body three']
    news.save(update_fields=['suggested_questions'])
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    monkeypatch.setattr('api.services.ai_execution.personal_clients_for_user', lambda user: [])
    monkeypatch.setattr('api.services.chatgpt_subscription.active_connection_for_user', lambda user: None)
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('reader initiated network'))
    response = api_client(a).post(f'/api/news/{news.pk}/suggested-questions/')
    assert response.status_code == 200
    assert not response.data['generated'] and response.data['context_scope'] == 'summary'
    assert all('secret from body' not in question for question in response.data['questions'])


def test_old_resolver_cannot_expose_private_source(world, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    a, b, make = world
    source, _ = make('private-source', subscriber=a)
    response = api_client(b).post('/api/smart-channels/resolve/', {'url': source.url}, format='json')
    assert response.status_code == 200
    assert response.data['matches'] == []


def test_available_summary_and_whitespace_match_sql_python(world):
    a, _, make = world
    _, news = make('available-summary', subscriber=a, state='available')
    news.full_content_completeness = 'summary'
    news.save(update_fields=['full_content_completeness'])
    assert not body_authorized_news(a).filter(pk=news.pk).exists()
    assert get_stored_article(a, news.pk).scope == 'summary'
    news.full_content_completeness = 'unknown'
    news.full_content = '\n\t\u2003'
    news.save(update_fields=['full_content_completeness', 'full_content'])
    assert not body_authorized_news(a).filter(pk=news.pk).exists()
    assert get_stored_article(a, news.pk).scope == 'summary'


def test_translation_and_tts_deny_before_cache_or_provider(world, monkeypatch):
    a, _, make = world
    source, news = make('restricted', subscriber=a)
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only')
    monkeypatch.setattr('api.services.tts_service.resolve_tts_content', lambda *a, **k: pytest.fail('unauthorized TTS cache lookup'))
    monkeypatch.setattr('api.services.shared_translations.get_shared_translation', lambda *a, **k: pytest.fail('unauthorized translation cache lookup'))
    client = api_client(a)
    assert client.get(f'/api/news/{news.pk}/tts/', {'scope': 'full'}).status_code == 409
    response = client.post(f'/api/news/{news.pk}/translate/')
    assert response.status_code == 200  # legacy endpoint reports errors as SSE
    assert b'full_content_not_ready' in b''.join(response.streaming_content)


def test_legacy_source_item_membership_and_origin_remain_distinct(world):
    from api.models import NewsSourceItem
    from api.services.source_policy import POLICIES
    a, b, make = world
    private, news = make('private-origin', subscriber=a)
    policy = next(p for p in POLICIES.values() if p.reading_policy != 'rss_summary_only')
    source, _ = Source.objects.get_or_create(name=policy.name, defaults={'url': 'https://publisher.example/'})
    SourcePublication.objects.update_or_create(source=source, defaults={'publication': 'public', 'reading_policy': 'standard', 'owner': 'paused'})
    NewsSourceItem.objects.create(news=news, source_key=policy.key, upstream_id='external-1', discovery_url=news.url)
    assert authorized_news(b).filter(pk=news.pk).exists()
    assert get_stored_article(b, news.pk).scope == 'summary'
    assert get_stored_article(a, news.pk).scope == 'full'


def test_preview_does_not_load_stored_full_body(world, monkeypatch):
    a, _, make = world
    _, news = make('large-preview', subscriber=a, state='available')
    news.full_content = 'body ' * 100000
    news.save(update_fields=['full_content'])
    monkeypatch.setattr('api.rss.access.get_stored_article', lambda *args: pytest.fail('list loaded full body'))
    response = api_client(a).get('/api/news/')
    assert response.status_code == 200
    assert response.data['results'][0]['has_full_content']
    assert len(response.content) < 3000


def test_paused_legacy_cached_body_still_readable_without_fetch(world, monkeypatch):
    a, _, make = world
    _, news = make('paused-cache', subscriber=a, owner='paused')
    monkeypatch.setattr('socket.socket.connect', lambda *args, **kwargs: pytest.fail('paused source fetched'))
    response = api_client(a).post(f'/api/news/{news.pk}/fetch-full/', {}, format='json')
    assert response.status_code == 410
    assert api_client(a).get(f'/api/news/{news.pk}/').data['full_content'] == news.full_content
    assert api_client(a).post(f'/api/news/{news.pk}/fetch-full/', {'force': True}, format='json').status_code == 410
