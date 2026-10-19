"""Add explicit BYOK translation cancellation/retry lifecycle.

Results belong to attempts, while only active source attempts are unique.
"""
from django.db import migrations, models
from django.utils import timezone
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



def reconcile_active_private_tasks(apps, schema_editor):
    """Fence older cross-key active duplicates before the user/source index."""
    Task = apps.get_model('api', 'ChatGPTTranslationTask')
    alias = schema_editor.connection.alias
    rows = list(Task.objects.using(alias).filter(
        api_connection__isnull=False, status__in=('queued', 'running'),
    ).order_by('user_id', 'news_id', 'source_hash', '-queued_at', '-id').values(
        'pk', 'user_id', 'news_id', 'source_hash', 'generation', 'status', 'run_token',
    ))
    seen = set()
    now = timezone.now()
    for row in rows:
        key = (row['user_id'], row['news_id'], row['source_hash'])
        if key not in seen:
            # Keep the most recently queued attempt as the recoverable current
            # row; older active rows are terminally fenced without deletion.
            seen.add(key)
            continue
        Task.objects.using(alias).filter(
            pk=row['pk'], generation=row['generation'], status=row['status'],
            run_token=row['run_token'],
        ).update(
            status='interrupted', run_token=None, lease_expires_at=None,
            error_code='worker_interrupted',
            error_message='升级时隔离较早的重复活动任务；已派发请求仍可能计费，不会自动重放。',
            finished_at=now, updated_at=now,
        )


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
        migrations.RunPython(reconcile_active_private_tasks, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='chatgpttranslationtask',
            constraint=models.UniqueConstraint(
                fields=('user', 'news', 'source_hash'),
                condition=models.Q(api_connection__isnull=False, status__in=('queued', 'running')),
                name='byok_translation_task_active_source',
            ),
        ),
    ]
