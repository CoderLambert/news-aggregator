"""Extend existing private translation records; retain all subscription rows."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('api', '0064_article_chat_turn')]
    operations = [
        migrations.AlterField(model_name='chatgptarticletranslation', name='connection',
            field=models.ForeignKey(to='api.chatgptsubscriptionconnection', null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE, related_name='translations')),
        migrations.AddField(model_name='chatgptarticletranslation', name='api_connection',
            field=models.ForeignKey(to='api.useraiconnection', null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE, related_name='private_translations')),
        migrations.AddConstraint(model_name='chatgptarticletranslation', constraint=models.CheckConstraint(
            condition=(models.Q(connection__isnull=False, api_connection__isnull=True) |
                       models.Q(connection__isnull=True, api_connection__isnull=False)),
            name='byok_translation_result_credential_xor')),
        migrations.AddConstraint(model_name='chatgptarticletranslation', constraint=models.UniqueConstraint(
            fields=['user', 'api_connection', 'news', 'source_hash'],
            condition=models.Q(api_connection__isnull=False), name='byok_translation_result_source')),
        migrations.AlterField(model_name='chatgpttranslationtask', name='connection',
            field=models.ForeignKey(to='api.chatgptsubscriptionconnection', null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE, related_name='translation_tasks')),
        migrations.AddField(model_name='chatgpttranslationtask', name='api_connection',
            field=models.ForeignKey(to='api.useraiconnection', null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE, related_name='private_translation_tasks')),
        migrations.AddConstraint(model_name='chatgpttranslationtask', constraint=models.CheckConstraint(
            condition=(models.Q(connection__isnull=False, api_connection__isnull=True) |
                       models.Q(connection__isnull=True, api_connection__isnull=False)),
            name='byok_translation_task_credential_xor')),
        migrations.AddConstraint(model_name='chatgpttranslationtask', constraint=models.UniqueConstraint(
            fields=['user', 'api_connection', 'news', 'source_hash'],
            condition=models.Q(api_connection__isnull=False), name='byok_translation_task_source')),
        migrations.AlterField(model_name='chatgpttranslationtask', name='connection_generation',
            field=models.PositiveBigIntegerField(null=True, blank=True)),
        migrations.AddField(model_name='chatgpttranslationtask', name='request_id',
            field=models.UUIDField(null=True, blank=True)),
        migrations.AddField(model_name='chatgpttranslationtask', name='request_hash',
            field=models.CharField(max_length=64, blank=True, default='')),
        migrations.AddField(model_name='chatgpttranslationtask', name='execution_snapshot',
            field=models.JSONField(default=dict)),
        migrations.AddConstraint(model_name='chatgpttranslationtask', constraint=models.UniqueConstraint(
            fields=['user', 'request_id'], condition=models.Q(api_connection__isnull=False),
            name='byok_translation_request')),
        migrations.AddConstraint(model_name='chatgpttranslationtask', constraint=models.CheckConstraint(
            condition=(models.Q(api_connection__isnull=True) |
                models.Q(connection_generation__isnull=True, shared_lease_task_id__isnull=True,
                         shared_lease_token__isnull=True, request_id__isnull=False)),
            name='byok_translation_private_only')),
    ]
