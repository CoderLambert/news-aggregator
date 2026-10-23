from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APIClient

from api.models import (Category, Source, News, NewsSourceItem, ChannelGroup,
                        ChannelGroupRoot, ChannelSubscription)
from api.services.source_policy import POLICIES
from api.services.sector_feeds import SECTOR_KEYS
from api.services.energy_keywords import matches_new_energy
from api.services.channel_catalog import subscription_status, catalog_defaults
from api.services.article_body_state import has_full_content

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)






@pytest.mark.parametrize('title, expected', [
    ('比亚迪发布新款电动车', True), ('小米 SU7 更新充电功能', True), ('电网储能项目并网', True),
    ('风电项目使用绿氢制备燃料', True), ('Tesla EV charging stations expand', True),
    ('New electric vehicles announced', True), ('固态动力电池量产', True),
    ('手机电池续航提升', False), ('小米发布手机新品', False), ('Developer tools for everyone', False),
    ('Apple battery replacement', False), ('Review of an ordinary camera', False),
])
def test_energy_keywords_do_not_admit_generic_technology(title, expected):
    assert matches_new_energy(title) is expected








@pytest.fixture
def sector_catalog(db):
    # Transactional tests flush data-migration rows. Reader tests must create
    # their own reviewed metadata and access grants, regardless of worker order.
    from api.models import SourcePublication
    Category.objects.get_or_create(name='医疗健康', defaults={'slug': 'sector-test-health'})
    names = {'PV Magazine 中文版', 'MedTech Dive', 'FDA 新闻稿',
             'MIT Tech Review AI', 'MIT 科技评论·生物技术'}
    policies = {policy.name: policy for policy in POLICIES.values()}
    for name in sorted(names):
        policy = policies[name]
        source, _ = Source.objects.get_or_create(name=name, defaults=catalog_defaults(policy))
        SourcePublication.objects.update_or_create(source=source, defaults={
            'publication': 'public', 'owner': 'legacy', 'reading_policy': policy.reading_policy})


@pytest.fixture
def reading_data(sector_catalog):
    category = Category.objects.get(name='医疗健康')
    domestic = Source.objects.get(name='PV Magazine 中文版')
    medical = Source.objects.get(name='MedTech Dive')
    stories = []
    for source in [domestic, medical]:
        stories.append(News.objects.create(title=source.name, content='shared query', url=source.url + 'news/test',
            source=source, category=category, publish_time=NOW))
    return domestic, medical, stories


@pytest.mark.django_db
def test_catalog_regions_candidate_and_medical_summary_only(reading_data):
    domestic, medical, stories = reading_data
    assert domestic.region == 'domestic' and medical.region == 'international'
    fda = Source.objects.get(name='FDA 新闻稿')
    assert subscription_status(fda) == ('inactive', 'feed_verification_pending')
    news = stories[1]
    news.full_content = 'Previously saved text'
    news.full_content_state = 'legacy'; news.save()
    assert not has_full_content(news)
    response = APIClient().get(f'/api/news/{news.pk}/')
    assert response.data['is_medical'] and response.data['reading_policy'] == 'rss_summary_only'
    assert response.data['full_content'] == '' and not response.data['has_full_content']
    user = User.objects.create_user('rss-reader')
    client = APIClient(); client.force_authenticate(user)
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')) as fetch:
        response = client.post(f'/api/news/{news.pk}/fetch-full/', {}, format='json')
    assert response.status_code == 410
    fetch.assert_not_called()


@pytest.mark.django_db
@patch('api.services.embedding.EmbeddingService.is_loaded', return_value=True)
@patch('api.services.search_index_control.index_version_is_current', return_value=True)
@patch('api.services.vector_store.VectorStoreService')
def test_regions_share_all_search_modes_and_group_intersection(vector, version, embedding, reading_data):
    domestic, medical, stories = reading_data
    vector.return_value.count.return_value = 2
    vector.return_value.search.return_value = [(n.id, .9) for n in stories]
    user = User.objects.create_user('regional-reader')
    root = ChannelGroupRoot.objects.create(user=user, name='Test root')
    group = ChannelGroup.objects.create(user=user, root=root, name='Selected feeds')
    for source in [domestic, medical]:
        subscription = ChannelSubscription.objects.create(user=user, source=source)
        group.subscriptions.add(subscription)
    client = APIClient(); client.force_authenticate(user)
    for mode in ['keyword', 'semantic', 'hybrid']:
        response = client.get('/api/news/', {'scope': 'group', 'group_id': group.id, 'region': 'domestic', 'search': 'shared query', 'mode': mode})
        assert response.status_code == 200
        assert response.data['count'] == 1
        assert response.data['results'][0]['id'] == stories[0].id
    for mode in ['semantic', 'hybrid']:
        with patch('api.services.search_index_control.index_version_is_current', return_value=False):
            response = client.get('/api/news/', {'region': 'international', 'search': 'shared query', 'mode': mode})
        assert response.data['count'] == 1 and response.data['results'][0]['id'] == stories[1].id
    assert client.get('/api/news/', {'region': 'invalid'}).status_code == 400
    assert client.get('/api/sources/', {'region': 'invalid'}).status_code == 400
    assert all(s['region'] == 'domestic' for s in client.get('/api/sources/', {'region': 'domestic'}).data)


@pytest.mark.django_db
def test_overlapping_publisher_channels_keep_primary_and_are_visible_in_both_groups(sector_catalog):
    primary = Source.objects.get(name='MIT Tech Review AI')
    # This membership fixture explicitly uses compatible summary policies.
    from api.models import SourcePublication
    SourcePublication.objects.filter(source=primary).update(reading_policy='rss_summary_only')
    category = Category.objects.get_or_create(name='科技', defaults={'slug': 'tech'})[0]
    news = News.objects.create(title='Clinical research', content='Original excerpt', source=primary, category=category,
        publish_time=NOW, url='https://www.technologyreview.com/news/1')
    NewsSourceItem.objects.create(news=news, source_key='mit_biotechnology',
        upstream_id='historical-shared-item', discovery_url=news.url)
    news.refresh_from_db(); assert news.source_id == primary.id
    medical = Source.objects.get(name='MIT 科技评论·生物技术')
    client = APIClient()
    response = client.get('/api/news/', {'source': medical.id, 'category': Category.objects.get(name='医疗健康').id})
    assert response.data['count'] == 1
    assert set(response.data['results'][0]['channel_ids']) == {primary.id, medical.id}
    assert response.data['results'][0]['is_medical']
    directory = client.get('/api/sources/').data
    assert next(s['news_count'] for s in directory if s['id'] == medical.id) == 1
    user = User.objects.create_user('multi-channel-reader')
    ChannelSubscription.objects.create(user=user, source=medical)
    client.force_authenticate(user)
    assert client.get('/api/news/', {'scope': 'subscribed'}).data['count'] == 1
    assert client.get('/api/news/', {'scope': 'subscribed', 'source': primary.id}).data['count'] == 1
