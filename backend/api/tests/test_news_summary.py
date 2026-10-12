import gzip
from unittest.mock import patch
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Category, Source, News
from api.serializers import NewsSummarySerializer

@pytest.fixture
def articles(db):
    category = Category.objects.create(name='Synthetic', slug='synthetic')
    source = Source.objects.create(name='Synthetic', url='https://example.com')
    return [News.objects.create(title=f'Synthetic article {i}', title_zh=f'合成文章{i}',
        content='Synthetic article paragraph. ' * 500, content_zh='合成新闻段落。' * 500,
        full_content='complete full body ' * 1000, category=category, source=source,
        url=f'https://example.com/{i}', publish_time=timezone.now()) for i in range(20)]

@pytest.mark.django_db
@pytest.mark.parametrize('body', ['', 'a' * 299, 'a' * 300, 'a' * 301, '新闻🙂' * 200])
def test_summary_boundaries(articles, body):
    article = articles[0]
    article.content = body
    article.content_zh = body
    data = NewsSummarySerializer(article).data
    assert data['summary'] == body[:300]
    assert data['summary_zh'] == body[:300]
    assert not {'content', 'content_zh', 'full_content', 'full_content_zh'} & data.keys()

@pytest.mark.django_db
def test_payload_detail_and_constant_queries(articles, django_assert_num_queries):
    client = APIClient()
    with django_assert_num_queries(2):
        response = client.get('/api/news/?representation=summary&page_size=20')
    assert response.status_code == 200
    assert response.data['count'] == 20
    assert len(response.data['results']) == 20
    with django_assert_num_queries(2):
        single = client.get('/api/news/?representation=summary&page_size=1')
    assert len(single.data['results']) == 1
    legacy = client.get('/api/news/?page_size=20')
    assert legacy.data['results'][0]['content'] == articles[-1].content
    assert len(response.content) < len(legacy.content) / 5
    assert len(gzip.compress(response.content, compresslevel=5)) < len(response.content) / 2
    detail = client.get(f'/api/news/{articles[0].pk}/')
    assert detail.data['content'] == articles[0].content
    assert detail.data['content_zh'] == articles[0].content_zh
    assert detail.data['full_content'] == articles[0].full_content

@pytest.mark.django_db
def test_summary_search_filter_pagination_and_fallback(articles):
    client = APIClient()
    url = '/api/news/?representation=summary&page_size=3&page=2&search=paragraph&order_by=time'
    response = client.get(url + f'&category={articles[0].category_id}&source={articles[0].source_id}')
    assert response.data['count'] == 20
    assert len(response.data['results']) == 3
    assert 'representation=summary' in response.data['next']
    assert all('summary' in item and 'content' not in item for item in response.data['results'])
    with patch('api.views.NewsListView._semantic_search', side_effect=RuntimeError('offline')):
        fallback = client.get(url + '&mode=semantic')
    assert fallback.data['search_mode_applied'] == 'keyword'
    assert all('summary' in item and 'content' not in item for item in fallback.data['results'])

@pytest.mark.django_db
@pytest.mark.parametrize('mode', ['semantic', 'hybrid'])
def test_ranked_search_summary_uses_constant_queries(articles, mode, django_assert_num_queries):
    client = APIClient()
    with patch('api.services.search_index_control.index_version_is_current', return_value=True), \
         patch('api.services.embedding.EmbeddingService.is_loaded', return_value=True), \
         patch('api.services.vector_store.VectorStoreService') as vector:
        vector.return_value.count.return_value = len(articles)
        vector.return_value.search.return_value = [(article.pk, 0.9) for article in articles]
        expected_queries = 2 if mode == 'semantic' else 3
        with django_assert_num_queries(expected_queries):
            response = client.get(f'/api/news/?representation=summary&search=paragraph&mode={mode}&page_size=20')
        assert response.data['search_mode_applied'] == mode
        assert response.data['count'] == 20
        assert len(response.data['results']) == 20
        assert all('summary' in item and 'content' not in item for item in response.data['results'])
