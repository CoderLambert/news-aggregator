import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def archive_legacy_chats(apps, schema_editor):
    ChatSession = apps.get_model('api', 'ChatSession')
    LegacyChatArchive = apps.get_model('api', 'LegacyChatArchive')
    database = schema_editor.connection.alias
    batch = []

    for session in ChatSession.objects.using(database).select_related('news').order_by('pk').iterator(chunk_size=500):
        batch.append(LegacyChatArchive(
            session_id=session.pk,
            news_id=session.news_id,
            title=session.news.title,
            url=session.news.url,
            messages=session.messages,
            created_at=session.created_at,
            updated_at=session.updated_at,
        ))
        if len(batch) >= 500:
            LegacyChatArchive.objects.using(database).bulk_create(batch, batch_size=500)
            batch.clear()

    if batch:
        LegacyChatArchive.objects.using(database).bulk_create(batch, batch_size=500)


def refuse_reverse(apps, schema_editor):
    raise IrreversibleError(
        'Legacy chats were archived without assigning them to users; restore from a pre-migration backup.'
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ('api', '0026_shared_article_translations'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LegacyChatArchive',
            fields=[
                ('session_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('news_id', models.BigIntegerField()),
                ('title', models.CharField(max_length=500)),
                ('url', models.URLField(max_length=500)),
                ('messages', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField()),
                ('updated_at', models.DateTimeField()),
            ],
            options={
                'verbose_name': '旧版对话归档',
                'verbose_name_plural': '旧版对话归档',
                'ordering': ['session_id'],
            },
        ),
        migrations.RunPython(archive_legacy_chats, reverse_code=refuse_reverse),
        migrations.DeleteModel(name='ChatSession'),
        migrations.CreateModel(
            name='ChatSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('messages', models.JSONField(blank=True, default=list, verbose_name='对话记录')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('revision', models.PositiveBigIntegerField(default=0)),
                ('generation', models.PositiveBigIntegerField(default=0)),
                ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_sessions', to='api.news')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='news_chat_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '对话会话',
                'verbose_name_plural': '对话会话',
                'constraints': [models.UniqueConstraint(fields=('user', 'news'), name='unique_user_news_chat')],
            },
        ),
    ]
