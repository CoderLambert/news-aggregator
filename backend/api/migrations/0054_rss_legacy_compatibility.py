"""Add ownership without rewriting historical content, translations or provenance.

Run with application writers stopped, as for any schema upgrade. Batches commit
independently so large archives do not require one long SQLite write transaction.
The forward migration is restartable; reverse is deliberately a no-op (rollback
uses a compatible app and keeps new data, never discards ownership/history).
"""

from hashlib import sha256

from django.db import migrations, transaction


# Frozen non-standard static policy names from the pre-RSS service registry.
# No current application code is imported while replaying historical migrations.
STATIC_READING_POLICIES = {
    'PV Magazine 中文版': 'public_rss', 'IT之家': 'public_rss', 'Electrek': 'public_rss',
    'InsideEVs': 'public_rss', 'Energy-Storage.news': 'rss_summary_only',
    'PV Magazine 国际版': 'public_rss', 'Canary Media': 'public_rss',
    'Electrive': 'public_rss', 'The Verge 交通': 'public_rss', 'Utility Dive': 'public_rss',
    'Windpower Monthly': 'rss_summary_only', '爱范儿': 'public_rss',
    'STAT News': 'rss_summary_only', 'MedTech Dive': 'rss_summary_only',
    'BioPharma Dive': 'rss_summary_only', 'FDA 新闻稿': 'public_rss',
    'MedCity News': 'rss_summary_only', 'Fierce Healthcare': 'rss_summary_only',
    'NIH 新闻稿': 'public_rss', 'MIT 科技评论·生物技术': 'rss_summary_only',
    'Ars Technica 健康': 'rss_summary_only', 'Nature Medicine': 'rss_summary_only',
    'NEJM': 'rss_summary_only', 'The Lancet': 'rss_summary_only',
    'BBC Health': 'rss_summary_only', 'ScienceDaily 健康': 'rss_summary_only',
}
BATCH_SIZE = 200


def initialize_legacy(apps, schema_editor):
    alias = schema_editor.connection.alias
    Source = apps.get_model('api', 'Source')
    SourceConfig = apps.get_model('api', 'SourceConfig')
    SourcePublication = apps.get_model('api', 'SourcePublication')
    News = apps.get_model('api', 'News')
    last_id = 0
    while True:
        sources = list(Source.objects.using(alias).filter(pk__gt=last_id).order_by('pk')[:BATCH_SIZE])
        if not sources:
            break
        configs = dict(SourceConfig.objects.using(alias).filter(
            source_id__in=[source.pk for source in sources],
        ).values_list('source_id', 'reading_policy'))
        with transaction.atomic(using=alias):
            for source in sources:
                reading_policy = configs.get(source.pk, STATIC_READING_POLICIES.get(source.name, 'standard'))
                SourcePublication.objects.using(alias).get_or_create(source_id=source.pk, defaults={
                    'publication': 'public', 'display_name': source.name,
                    'reading_policy': reading_policy, 'owner': 'legacy',
                    'epoch': 1, 'policy_version': 1,
                })
        last_id = sources[-1].pk
    last_id = 0
    while True:
        rows = list(News.objects.using(alias).filter(pk__gt=last_id).order_by('pk').only(
            'pk', 'source_id', 'full_content', 'body_owner_source_id', 'body_owner_binding_id',
            'full_content_hash',
        )[:BATCH_SIZE])
        if not rows:
            break
        for row in rows:
            if row.body_owner_source_id is None and row.body_owner_binding_id is None:
                row.body_owner_source_id = row.source_id
            if not row.full_content_hash:
                # Exact bytes: no strip, LF conversion, unicode normalization or Markdown repair.
                row.full_content_hash = sha256(row.full_content.encode('utf-8')).hexdigest()
        with transaction.atomic(using=alias):
            News.objects.using(alias).bulk_update(rows, ['body_owner_source', 'full_content_hash'], batch_size=BATCH_SIZE)
        last_id = rows[-1].pk


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('api', '0053_rss_core_schema')]
    operations = [migrations.RunPython(initialize_legacy, migrations.RunPython.noop)]
