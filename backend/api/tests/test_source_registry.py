import pytest

from api.models import Category, CrawlerTarget, FeedState, Source, SourceConfig, SourceEndpoint
from api.services.crawler_control import sync_crawler_targets
from api.services.feed_state import prepare_feed_request
from api.services.source_policy import policy_for_key
from api.services.source_registry import CODE_SPIDERS, runtime_registry


@pytest.fixture
def dynamic_source(db):
    category, _ = Category.objects.get_or_create(name='医疗健康', defaults={'slug': 'medical-health'})
    source = Source.objects.create(
        name='测试官方频道', url='https://health.example.cn/', region='domestic',
        country='CN', language='zh', source_type='news',
    )
    config = SourceConfig.objects.create(
        source_key='test_official_health', source=source, publisher_name='测试机构',
        channel_name=source.name, category=category, status='approved',
        probed_config_version=1, approved_config_version=1,
    )
    SourceEndpoint.objects.create(
        source_config=config, kind='rss', url='https://health.example.cn/feed.xml',
        allowed_domains=['health.example.cn'], request_interval_seconds=600,
    )
    return config


@pytest.mark.django_db
def test_registry_merges_database_sources_without_overriding_code(dynamic_source):
    registry = runtime_registry()
    assert registry[dynamic_source.source_key].maintenance == 'database'
    assert registry[dynamic_source.source_key].spider == 'dynamic_source'
    assert registry['bbc'].maintenance == 'code'

    dynamic_source.source_key = 'bbc'
    dynamic_source.source = None
    dynamic_source.save(force_insert=True)
    assert runtime_registry()['bbc'].maintenance == 'code'


@pytest.mark.django_db
def test_dynamic_policy_and_target_default_are_versioned_and_disabled(dynamic_source):
    policy = policy_for_key(dynamic_source.source_key)
    assert policy.name == '测试官方频道'
    assert policy.domains == ('health.example.cn',)
    assert policy.contract_version == '1'
    sync_crawler_targets()
    target = CrawlerTarget.objects.get(pk=dynamic_source.source_key)
    assert target.enabled is False

    first = prepare_feed_request(dynamic_source.source_key, policy.feed_url)
    dynamic_source.config_version = 2
    dynamic_source.approved_config_version = 2
    dynamic_source.save(update_fields=['config_version', 'approved_config_version'])
    second = prepare_feed_request(dynamic_source.source_key, policy.feed_url)
    assert first.state_id != second.state_id
    assert set(FeedState.objects.filter(source_key=dynamic_source.source_key).values_list('config_version', flat=True)) == {'1', '2'}


def test_crawl_command_parser_has_no_import_time_source_choices():
    from api.management.commands.crawl import Command, SPIDERS
    parser = Command().create_parser('manage.py', 'crawl')
    assert parser.parse_args(['future_database_source']).spider == 'future_database_source'
    assert SPIDERS is CODE_SPIDERS
