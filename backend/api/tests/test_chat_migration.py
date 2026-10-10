from datetime import datetime, timezone as datetime_timezone
import os
import subprocess
import sys

import pytest
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor


LEGACY_TARGET = ('api', '0026_shared_article_translations')
OWNERSHIP_TARGET = ('api', '0027_chat_ownership')


def _exercise_migration():
    import django

    django.setup()

    from django.db import connection

    executor = MigrationExecutor(connection)
    executor.migrate([LEGACY_TARGET])
    old_apps = executor.loader.project_state([LEGACY_TARGET]).apps
    Source = old_apps.get_model('api', 'Source')
    Category = old_apps.get_model('api', 'Category')
    News = old_apps.get_model('api', 'News')
    ChatSession = old_apps.get_model('api', 'ChatSession')

    source = Source.objects.using('default').create(
        name='Legacy source',
        url='https://legacy.example.test',
    )
    category = Category.objects.using('default').create(
        name='Legacy category',
        slug='legacy-category',
    )
    legacy_messages = [
        [],
        {'shape': 'non-list JSON is retained'},
        'legacy JSON scalar',
    ]
    legacy_timestamps = []
    for index, messages in enumerate(legacy_messages, start=1):
        news = News.objects.using('default').create(
            title=f'Legacy title {index}',
            content='Legacy content',
            publish_time=datetime(2020, 1, index, tzinfo=datetime_timezone.utc),
            source_id=source.pk,
            category_id=category.pk,
            url=f'https://legacy.example.test/article-{index}',
        )
        session = ChatSession.objects.using('default').create(news_id=news.pk, messages=messages)
        created_at = datetime(2021, 2, index, 3, 4, 5, tzinfo=datetime_timezone.utc)
        updated_at = datetime(2022, 3, index, 6, 7, 8, tzinfo=datetime_timezone.utc)
        ChatSession.objects.using('default').filter(pk=session.pk).update(
            created_at=created_at,
            updated_at=updated_at,
        )
        legacy_timestamps.append((created_at, updated_at))

    executor = MigrationExecutor(connection)
    executor.migrate([OWNERSHIP_TARGET])
    migrated_apps = executor.loader.project_state([OWNERSHIP_TARGET]).apps
    Archive = migrated_apps.get_model('api', 'LegacyChatArchive')
    OwnedChatSession = migrated_apps.get_model('api', 'ChatSession')
    archived = list(Archive.objects.using('default').order_by('session_id'))

    assert len(archived) == 3
    assert OwnedChatSession.objects.using('default').count() == 0
    for index, (record, messages, timestamps) in enumerate(
        zip(archived, legacy_messages, legacy_timestamps, strict=True),
        start=1,
    ):
        created_at, updated_at = timestamps
        assert record.session_id == index
        assert record.news_id == index
        assert record.title == f'Legacy title {index}'
        assert record.url == f'https://legacy.example.test/article-{index}'
        assert record.messages == messages
        assert record.created_at == created_at
        assert record.updated_at == updated_at

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Archive._meta.db_table)
    assert all(details['foreign_key'] is None for details in constraints.values())

    with pytest.raises(IrreversibleError, match='restore from a pre-migration backup'):
        MigrationExecutor(connection).migrate([LEGACY_TARGET])

    after_reverse_attempt = MigrationExecutor(connection)
    assert OWNERSHIP_TARGET in after_reverse_attempt.loader.applied_migrations
    after_apps = after_reverse_attempt.loader.project_state([OWNERSHIP_TARGET]).apps
    assert after_apps.get_model('api', 'LegacyChatArchive').objects.using('default').count() == 3
    assert after_apps.get_model('api', 'ChatSession').objects.using('default').count() == 0
    connection.close()


def test_0027_archives_every_legacy_session_and_refuses_reverse(tmp_path):
    # Run the migration against its own SQLite file in an unwrapped Django
    # process so pytest-django's allowed-database guard cannot hide what is
    # being tested. The caller's test DB is never opened by this probe.
    environment = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'HOME': os.environ['HOME'],
        'PYTHONPATH': os.environ['PYTHONPATH'],
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_ENV': 'development',
        'RUN_MAIN': 'true',
        'DJANGO_DB_PATH': str(tmp_path / 'chat-migration.sqlite3'),
    }
    result = subprocess.run(
        [sys.executable, os.path.abspath(__file__), '--migration-probe'],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}'


if __name__ == '__main__' and sys.argv[1:] == ['--migration-probe']:
    _exercise_migration()
