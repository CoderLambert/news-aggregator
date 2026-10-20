"""Remove only unused migration-seeded legacy catalog rows, preserving history."""
from django.db import migrations
from importlib import import_module


def retire_empty(apps, schema_editor):
    Source = apps.get_model('api', 'Source')
    Publication = apps.get_model('api', 'SourcePublication')
    alias = schema_editor.connection.alias
    seeded = dict(import_module('api.migrations.0040_initialize_channel_catalog').CHANNELS)
    for source in Source.objects.using(alias).filter(publication__owner='legacy', name__in=seeded).iterator():
        if source.url != seeded[source.name]['url']:
            continue
        # No import of today's policy list and no removal of referenced history.
        references = [relation for relation in Source._meta.related_objects
                      if relation.related_model != Publication]
        if any(relation.related_model.objects.using(alias).filter(
                **{relation.field.attname: source.pk}).exists() for relation in references):
            continue
        Publication.objects.using(alias).filter(source_id=source.pk).delete()
        Source.objects.using(alias).filter(pk=source.pk).delete()


class Migration(migrations.Migration):
    dependencies = [('api', '0073_rss_initialization_boundary')]
    operations = [migrations.RunPython(retire_empty, migrations.RunPython.noop)]
