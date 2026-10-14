import pytest
from django.utils import timezone
from types import SimpleNamespace

from api.models import Category, CrawlerTarget, FeedState, Source, SourceConfig, SourceEndpoint
from api.services.crawler_control import create_crawl_batch, sync_crawler_targets
from api.services.feed_state import prepare_feed_request
from api.services.source_policy import policy_for_key
from api.services.source_registry import CODE_SPIDERS, runtime_registry, source_snapshot


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
        probed_config_version=1, probed_at=timezone.now(),
        approved_config_version=1, approved_at=timezone.now(),
    )
    SourceEndpoint.objects.create(
        source_config=config, kind='rss', url='https://health.example.cn/feed.xml',
        allowed_domains=['health.example.cn'], request_interval_seconds=600,
    )
    return config


@pytest.mark.django_db
def test_dynamic_run_snapshot_is_complete_and_immutable(dynamic_source):
    snapshot = source_snapshot(dynamic_source.source_key)
    assert snapshot['source_key'] == dynamic_source.source_key
    assert snapshot['config_version'] == 1
    assert snapshot['endpoint']['url'] == 'https://health.example.cn/feed.xml'
    dynamic_source.channel_name = '后续修改'
    dynamic_source.config_version = 2
    dynamic_source.save(update_fields=['channel_name', 'config_version'])
    assert snapshot['policy']['name'] == '测试官方频道'


@pytest.mark.django_db
def test_single_run_persists_snapshot_while_target_remains_disabled(dynamic_source):
    sync_crawler_targets()
    batch, active = create_crawl_batch(
        trigger='manual', spider_names=[dynamic_source.source_key], allow_disabled=True,
    )
    assert active == []
    run = batch.runs.get()
    assert run.target.enabled is False
    assert run.config_snapshot['config_version'] == 1
    assert run.config_snapshot['endpoint']['url'] == 'https://health.example.cn/feed.xml'


@pytest.mark.django_db
def test_seeded_domestic_sources_are_never_scheduler_enabled():
    expected = {
        'chinanews_health': ('probed', 'article'), 'china_cdc_news': ('probed', 'article'),
        'nhc_news': ('blocked', 'article'), 'nhsa_news': ('probed', 'article'),
        'nmpa_news': ('blocked', 'article'), 'nmpa_udi_daily': ('probed', 'regulatory_data'),
    }
    configs = SourceConfig.objects.in_bulk(expected)
    assert {key: (value.status, value.content_kind) for key, value in configs.items()} == expected
    assert not CrawlerTarget.objects.filter(pk__in=expected, enabled=True).exists()


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


def test_all_source_command_freezes_dynamic_snapshots_before_subprocesses(monkeypatch):
    from api.management.commands import crawl
    from api.services.source_registry import RuntimeSource
    snapshot = {'schema_version': 1, 'source_key': 'future_database_source'}
    captured = []
    monkeypatch.setattr(crawl, 'runtime_registry', lambda: {
        'future_database_source': RuntimeSource(
            'future_database_source', 'dynamic_source', 'database', '未来来源', 1, 'approved',
        ),
    })
    monkeypatch.setattr(crawl, 'current_source_snapshot', lambda key: {**snapshot, 'requested_key': key})
    def run(*args, **kwargs):
        captured.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='NEWSHUB_CRAWL_RESULT {"outcome":"updated"}\n')
    monkeypatch.setattr(crawl.subprocess, 'run', run)
    crawl.Command()._crawl_all_serially()
    assert captured[0]['NEWS_SOURCE_SNAPSHOT']
    assert 'future_database_source' in captured[0]['NEWS_SOURCE_SNAPSHOT']
