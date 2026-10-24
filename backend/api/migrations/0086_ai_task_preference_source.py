from django.db import migrations, models


def backfill_selection_sources(apps, schema_editor):
    Preference = apps.get_model('api', 'UserAITaskPreference')
    Preference.objects.filter(model_config_id__isnull=False).update(selection_source='byok')
    Preference.objects.filter(task_kind='default', model_config_id__isnull=True).update(selection_source='unset')
    Preference.objects.exclude(task_kind='default').filter(model_config_id__isnull=True).update(selection_source='inherit')


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0085_channel_group_hierarchy'),
    ]

    operations = [
        migrations.AddField(
            model_name='useraitaskpreference',
            name='selection_source',
            field=models.CharField(
                choices=[
                    ('unset', 'unset'),
                    ('inherit', 'inherit'),
                    ('byok', 'byok'),
                    ('chatgpt_subscription', 'chatgpt_subscription'),
                ],
                default='inherit',
                max_length=32,
            ),
        ),
        migrations.RunPython(backfill_selection_sources, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='useraitaskpreference',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(selection_source='byok', model_config__isnull=False)
                    | models.Q(
                        selection_source__in=('unset', 'inherit', 'chatgpt_subscription'),
                        model_config__isnull=True,
                    )
                ),
                name='user_ai_task_preference_source_model',
            ),
        ),
        migrations.AddConstraint(
            model_name='useraitaskpreference',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(task_kind='default', selection_source__in=('unset', 'byok'))
                    | ~models.Q(task_kind='default')
                ),
                name='user_ai_task_preference_default_source',
            ),
        ),
    ]
