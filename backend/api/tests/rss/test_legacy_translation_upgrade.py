import importlib
from types import SimpleNamespace
from hashlib import sha256
import pytest
from django.apps import apps
from django.db import connection
from django.utils import timezone
from api.models import Category, LegacyTranslationSnapshot, News, Source

pytestmark = pytest.mark.django_db


def test_upgrade_binds_exact_legacy_bytes_idempotently_without_rewriting_article():
    source = Source.objects.create(name='Upgrade fixture', url='https://example.com')
    values = dict(title=' Title ', title_zh=' 旧标题 ', content='Summary\r\n', content_zh='摘要\r\n',
                  full_content='```py\nprint(1)\n```\n', full_content_zh='正文译文\n')
    news = News.objects.create(**values, source=source, category=Category.objects.create(name='Upgrade', slug='upgrade'),
                              url='https://example.com/upgrade', publish_time=timezone.now())
    migration = importlib.import_module('api.migrations.0059_bind_retained_legacy_translations')
    for _ in range(2):
        migration.freeze_legacy(apps, SimpleNamespace(connection=connection))
    assert LegacyTranslationSnapshot.objects.filter(news=news).count() == 3
    for field in ('title', 'content', 'full_content'):
        record = LegacyTranslationSnapshot.objects.get(news=news, field=field)
        assert record.source_text == values[field]
        assert record.source_hash == sha256(values[field].encode()).hexdigest()
        assert record.translated_text == values[field + '_zh'] and record.origin == 'legacy'
    news.refresh_from_db()
    assert all(getattr(news, field) == value for field, value in values.items())
