"""Freeze retained compatibility translations at the stopped-writer upgrade point.

No provider or user attribution is invented. Exact source/translation bytes are
retained as legacy evidence; current readers still require matching source hashes
and current article/body authorization. Reversal keeps this historical evidence.
"""
from hashlib import sha256
from django.db import migrations, transaction


def freeze_legacy(apps, schema_editor):
    alias = schema_editor.connection.alias
    News = apps.get_model('api', 'News')
    Snapshot = apps.get_model('api', 'LegacyTranslationSnapshot')
    last_id = 0
    fields = ('title', 'content', 'full_content')
    while True:
        rows = list(News.objects.using(alias).filter(pk__gt=last_id).order_by('pk').only(
            'pk', *fields, *(field + '_zh' for field in fields))[:20])
        if not rows:
            break
        with transaction.atomic(using=alias):
            for row in rows:
                for field in fields:
                    source, translated = getattr(row, field), getattr(row, field + '_zh')
                    if not translated:
                        continue
                    Snapshot.objects.using(alias).get_or_create(news_id=row.pk, field=field,
                        source_hash=sha256(source.encode('utf-8')).hexdigest(),
                        translation_hash=sha256(translated.encode('utf-8')).hexdigest(),
                        defaults={'source_text': source, 'translated_text': translated, 'origin': 'legacy'})
        last_id = rows[-1].pk


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('api', '0058_private_translation_versions')]
    operations = [migrations.RunPython(freeze_legacy, migrations.RunPython.noop)]
