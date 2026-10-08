import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps


def _pipeline():
    from news_crawler import pipelines

    return pipelines


def test_crawl_only_mode_is_opt_in(monkeypatch):
    pipelines = _pipeline()
    monkeypatch.delenv('NEWS_CRAWL_ONLY', raising=False)
    assert pipelines._ai_side_effects_enabled()

    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    assert not pipelines._ai_side_effects_enabled()


def test_crawl_only_clamps_spider_rates_and_enables_autothrottle():
    from scrapy.settings import Settings
    from api.management.commands.crawl import _apply_crawl_only_politeness

    settings = Settings({
        'DOWNLOAD_DELAY': 0.5,
        'CONCURRENT_REQUESTS': 16,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 5,
    })
    _apply_crawl_only_politeness(settings)

    assert settings.getfloat('DOWNLOAD_DELAY') == 3.0
    assert settings.getint('CONCURRENT_REQUESTS') == 4
    assert settings.getint('CONCURRENT_REQUESTS_PER_DOMAIN') == 1
    assert settings.getbool('AUTOTHROTTLE_ENABLED') is True
    assert settings.getfloat('AUTOTHROTTLE_MAX_DELAY') == 60.0


def test_crawl_summary_reports_each_spider_with_stable_counts():
    from api.management.commands.crawl import _format_crawl_summary

    summary = _format_crawl_summary('bbc', {
        'finish_reason': 'finished',
        'item_scraped_count': 12,
        'downloader/response_count': 15,
        'downloader/response_status_count/200': 13,
        'downloader/response_status_count/403': 2,
        'log_count/ERROR': 1,
    })

    assert summary == (
        '爬虫汇总 source=bbc finish=finished items=12 '
        'responses=15 errors=1 http=200:13,403:2'
    )


def test_crawl_once_creates_its_ignored_lock_directory(tmp_path):
    if shutil.which('flock') is None:
        pytest.skip('flock is not installed')
    project = tmp_path / 'project'
    scripts = project / 'scripts'
    backend = project / 'backend'
    python = backend / 'venv' / 'bin' / 'python'
    scripts.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / 'scripts' / 'crawl_once.sh'
    script = scripts / 'crawl_once.sh'
    script.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
    script.chmod(0o755)
    python.write_text('#!/usr/bin/env bash\nexit 0\n', encoding='utf-8')
    python.chmod(0o755)

    result = subprocess.run([str(script), 'bbc'], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert (project / 'logs' / 'crawler.lock').is_file()


def test_crawl_only_short_circuits_ai_helpers(monkeypatch):
    pipelines = _pipeline()
    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')

    news = SimpleNamespace(
        id=1,
        title='An English article title',
        content='An English article body.',
        title_zh='',
        content_zh='',
    )
    with (
        patch.object(pipelines, 'translate') as translate,
        patch.object(pipelines, 'is_chinese') as is_chinese,
        patch('api.services.vector_store.VectorStoreService') as vector_store,
    ):
        assert pipelines._find_similar_titles(news.title) is None
        pipelines._index_news(news.id, news.title, news.content)
        pipelines._try_translate(news)

    translate.assert_not_called()
    is_chinese.assert_not_called()
    vector_store.assert_not_called()


@pytest.mark.django_db
def test_crawl_only_stores_new_items_without_ai_helpers(monkeypatch):
    pipelines = _pipeline()
    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    item = {
        'title': 'Crawl-only mode preserves the original article',
        'content': 'Public article body from the configured web.dev source.',
        'author': '',
        'publish_time': None,
        'source_name': 'web.dev',
        'category_name': 'crawl-only-test',
        'url': 'https://web.dev/blog/crawl-only-test-20261008',
        'cover_image': '',
    }

    with (
        patch.object(pipelines, 'close_old_connections'),
        patch.object(pipelines, '_find_similar_titles') as similarity,
        patch.object(pipelines, '_index_news') as index_news,
        patch.object(pipelines, '_try_translate') as try_translate,
    ):
        news = pipelines._save_item_sync(item)

    assert news.url == item['url']
    assert news.content == item['content']
    assert news.translation_status == 'pending'
    assert news.related_to_id is None
    similarity.assert_not_called()
    index_news.assert_not_called()
    try_translate.assert_not_called()


def test_crawl_only_does_not_preload_embedding_model(monkeypatch):
    import api.apps as api_apps

    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    monkeypatch.delenv('RUN_MAIN', raising=False)
    monkeypatch.delenv('DJANGO_AUTORELOAD_ENV', raising=False)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setattr(api_apps, 'sys', SimpleNamespace(modules={}, argv=['manage.py', 'crawl']))

    with patch('api.services.embedding.EmbeddingService.preload') as preload:
        apps.get_app_config('api').ready()

    preload.assert_not_called()


def test_crawl_only_honors_robots_txt(monkeypatch):
    import importlib

    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    import news_crawler.settings as crawler_settings
    importlib.reload(crawler_settings)
    assert crawler_settings.ROBOTSTXT_OBEY is True
    assert crawler_settings.TELNETCONSOLE_ENABLED is False


def test_default_crawler_robots_setting_is_unchanged(monkeypatch):
    import importlib

    monkeypatch.delenv('NEWS_CRAWL_ONLY', raising=False)
    import news_crawler.settings as crawler_settings
    importlib.reload(crawler_settings)
    assert crawler_settings.ROBOTSTXT_OBEY is False
    assert crawler_settings.TELNETCONSOLE_ENABLED is True
