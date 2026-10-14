from datetime import datetime, timezone

import pytest
from django.test import override_settings

from api.models import Category, NewsSourceItem, Source, SourceConfig, SourceEndpoint
from api.services.article_fetcher.types import FullContentCandidate
from api.services.article_fetcher.validators import validate_candidate
from api.services.dynamic_source_parsing import parse_html_list, parse_json_list, structured_entry_item
from api.services.news_ingestion import ingest_item
from api.services.source_policy import policy_for_key


@pytest.fixture
def approved_dynamic_source(db):
    category, _ = Category.objects.get_or_create(name='医疗健康', defaults={'slug': 'medical-health'})
    source = Source.objects.create(name='测试卫生频道', url='https://health.example.cn/news/')
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    config = SourceConfig.objects.create(
        source_key='fixture_health', source=source, publisher_name='测试卫生机构',
        channel_name=source.name, category=category, status='approved', reading_policy='summary_only',
        probed_config_version=1, probed_at=now, approved_config_version=1, approved_at=now,
    )
    endpoint = SourceEndpoint.objects.create(
        source_config=config, kind='json', url='https://health.example.cn/api/news',
        allowed_domains=['health.example.cn'], parser_config={}, max_items=2,
    )
    return config, endpoint


def endpoint_dict(endpoint, **overrides):
    result = {
        'kind': endpoint.kind, 'url': endpoint.url, 'allowed_domains': endpoint.allowed_domains,
        'parser_config': endpoint.parser_config, 'max_response_bytes': endpoint.max_response_bytes,
        'max_items': endpoint.max_items,
    }
    result.update(overrides)
    return result


@pytest.mark.django_db
def test_json_mapping_is_bounded_and_rejects_cross_domain_links(approved_dynamic_source):
    config, model = approved_dynamic_source
    endpoint = endpoint_dict(model, parser_config={
        'list_path': 'data.items', 'next_path': 'data.next',
        'fields': {'identity': 'id', 'title': 'headline', 'link': 'url',
                   'summary': 'excerpt', 'published': 'published_at'},
    })
    body = (b'{"data":{"items":['
            b'{"id":"1","headline":"First","url":"/news/1","excerpt":"Summary","published_at":"2026-10-15T00:00:00Z"},'
            b'{"id":"2","headline":"Second","url":"https://evil.example/news/2","published_at":"2026-10-14"},'
            b'{"id":"3","headline":"Ignored","url":"/news/3","published_at":"2026-10-13"}],'
            b'"next":"/api/news?page=2"}}')
    rows, next_url = parse_json_list(body, endpoint)
    assert len(rows) == 2
    assert next_url == 'https://health.example.cn/api/news?page=2'
    item = structured_entry_item(rows[0], config.source_key, endpoint)
    assert item['content'] == 'Summary'
    assert item['publish_time'] == datetime(2026, 10, 15, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match='invalid_identity'):
        structured_entry_item(rows[1], config.source_key, endpoint)


@pytest.mark.django_db
def test_html_css_parser_handles_regular_and_inert_cms_markup(approved_dynamic_source):
    config, model = approved_dynamic_source
    endpoint = endpoint_dict(model, kind='html', parser_config={
        'list_item': 'record li', 'title': 'a', 'link': 'a', 'summary': 'p', 'date': 'span',
    })
    body = ('<html><script type="text/xml"><datastore><record><![CDATA['
            '<li><a href="/news/7">Official update</a><span>2026-10-15</span><p>Short abstract</p></li>'
            ']]></record></datastore></script></html>').encode()
    rows, next_url = parse_html_list(body, endpoint)
    assert next_url == ''
    assert rows == [{'identity': 'https://health.example.cn/news/7', 'title': 'Official update',
                     'link': 'https://health.example.cn/news/7', 'summary': 'Short abstract',
                     'published': '2026-10-15', 'content': ''}]
    item = structured_entry_item(rows[0], config.source_key, endpoint)
    assert item['content_kind'] == 'article'
    assert item['publish_time_inferred'] is True
    assert policy_for_key(config.source_key).reading_policy == 'rss_summary_only'


@pytest.mark.django_db
def test_dynamic_summary_ingests_through_source_mapping_without_full_body(approved_dynamic_source):
    config, model = approved_dynamic_source
    endpoint = endpoint_dict(model)
    item = structured_entry_item({
        'identity': 'official-9', 'title': '公共卫生公告', 'link': '/news/9',
        'summary': '这是来源提供的摘要。', 'published': '2026-10-15T00:00:00Z',
    }, config.source_key, endpoint)
    result = ingest_item(item)
    assert result.receipt_outcome == 'committed'
    mapping = NewsSourceItem.objects.get(source_key=config.source_key, upstream_id='official-9')
    assert mapping.news.content == '这是来源提供的摘要。'
    assert mapping.news.full_content == ''
    assert mapping.metadata['publisher_name'] == '测试卫生机构'
    assert mapping.metadata['endpoint_kind'] == 'json'


@pytest.mark.django_db
def test_approved_official_html_candidate_can_commit_but_summary_remains_separate(approved_dynamic_source):
    config, model = approved_dynamic_source
    config.reading_policy = 'official_html'
    config.official_html_full_content_allowed = True
    config.save(update_fields=['reading_policy', 'official_html_full_content_allowed'])
    endpoint = endpoint_dict(model, kind='html')
    item = structured_entry_item({
        'identity': 'official-10', 'title': '官方卫生公告', 'link': '/news/10',
        'summary': '这是与正文分离保存的摘要。', 'published': '2026-10-15T00:00:00Z',
    }, config.source_key, endpoint)
    candidate = FullContentCandidate(
        config.source_key, 'official-10', item['url'], item['url'], None, item['title'], 'article',
        'official_html_selector', 'html', 'full',
        '<article><p>这是经过审批和选择器边界的官方网页正文。</p><p>第二段独立内容。</p></article>',
        None, None, datetime.now(timezone.utc), request_chain=(item['url'],),
    )
    assert validate_candidate(candidate, expected_url=item['url'], expected_title=item['title'],
                              summary=item['summary']).ok
    item['body_candidate'] = candidate
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True,
                           STRUCTURED_BODY_SOURCE_KEYS=(config.source_key,)):
        result = ingest_item(item)
    assert result.body_committed is True
    mapping = NewsSourceItem.objects.get(source_key=config.source_key, upstream_id='official-10')
    assert mapping.news.content == '这是与正文分离保存的摘要。'
    assert '第二段独立内容' in mapping.news.full_content
