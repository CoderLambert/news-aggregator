import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import Category, News, Source


@pytest.fixture
def cat(db):
    return Category.objects.create(name='统计测试', slug='stats-test')


def _source(name):
    return Source.objects.create(name=name, url=f'https://{name.lower()}.example.com', language='en')


def _news(source, cat, **overrides):
    defaults = dict(
        title=f'{source.name} article',
        content='Summary',
        publish_time=timezone.now(),
        source=source,
        category=cat,
        url=f'https://{source.name.lower()}.example.com/{News.objects.count() + 1}',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


@pytest.mark.django_db
def test_full_content_stats_json_output_structure(cat):
    src = _source('StatsA')
    _news(src, cat, full_content='body', full_content_fetch_status='success', full_content_fetch_provider='jina')
    _news(src, cat, full_content_fetch_status='network_error', full_content_fetch_error='timeout', full_content_retry_count=2)

    out = StringIO()
    call_command('full_content_stats', '--json', stdout=out)
    data = json.loads(out.getvalue())

    assert data['total'] == 2
    assert data['with_full_content'] == 1
    assert data['coverage'] == 0.5
    assert data['status']['success'] == 1
    assert data['status']['network_error'] == 1
    assert data['sources']['StatsA'] == 2
    assert data['providers']['jina'] == 1
    assert data['top_errors']['timeout'] == 1
    assert data['retry_counts']['2'] == 1


@pytest.mark.django_db
def test_full_content_stats_filters_by_source(cat):
    src_a = _source('StatsA')
    src_b = _source('StatsB')
    _news(src_a, cat, full_content='body', full_content_fetch_status='success', full_content_fetch_provider='jina')
    _news(src_b, cat, full_content_fetch_status='failed', full_content_fetch_provider='scrapy_http')

    out = StringIO()
    call_command('full_content_stats', '--source', 'StatsA', '--json', stdout=out)
    data = json.loads(out.getvalue())

    assert data['total'] == 1
    assert data['sources'] == {'StatsA': 1}
    assert data['providers'] == {'jina': 1}


@pytest.mark.django_db
def test_full_content_stats_text_output_includes_provider_distribution(cat):
    src = _source('StatsText')
    _news(src, cat, full_content='body', full_content_fetch_status='success', full_content_fetch_provider='scrapy_http')

    out = StringIO()
    call_command('full_content_stats', stdout=out)

    text = out.getvalue()
    assert 'total: 1' in text
    assert 'coverage: 1.000' in text
    assert 'providers:' in text
    assert 'scrapy_http: 1' in text
