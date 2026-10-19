"""Add explicit BYOK translation cancellation/retry lifecycle.

Results belong to attempts, while only active source attempts are unique.
"""
from django.db import migrations, models
import django.db.models.deletion


def link_existing_private_results(apps, schema_editor):
    Task = apps.get_model('api', 'ChatGPTTranslationTask')
    Result = apps.get_model('api', 'ChatGPTArticleTranslation')
    alias = schema_editor.connection.alias
    for task in Task.objects.using(alias).filter(
        api_connection__isnull=False, status='succeeded',
    ).iterator():
        result = task.result if isinstance(task.result, dict) else {}
        result_id = result.get('result_id')
        if type(result_id) is not int:
            continue
        Result.objects.using(alias).filter(
            pk=result_id, task__isnull=True, user_id=task.user_id,
            api_connection_id=task.api_connection_id, news_id=task.news_id,
            source_hash=task.source_hash,
        ).update(task_id=task.pk)


class Migration(migrations.Migration):
    dependencies = [('api', '0065_byok_private_translation')]

    operations = [
        migrations.AddField(
            model_name='chatgptarticletranslation', name='task',
            field=models.OneToOneField(
                to='api.chatgpttranslationtask', null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL, related_name='private_result',
            ),
        ),
        migrations.RunPython(link_existing_private_results, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='chatgptarticletranslation', name='byok_translation_result_source',
        ),
        migrations.RemoveConstraint(
            model_name='chatgpttranslationtask', name='byok_translation_task_source',
        ),
        migrations.AddConstraint(
            model_name='chatgpttranslationtask',
            constraint=models.UniqueConstraint(
                fields=('user', 'news', 'source_hash'),
                condition=models.Q(api_connection__isnull=False, status__in=('queued', 'running')),
                name='byok_translation_task_active_source',
            ),
        ),
    ]
