from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0026_shared_article_translations'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserNewsChatSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('messages', models.JSONField(blank=True, default=list, verbose_name='对话记录')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='private_chat_sessions', to='api.news')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='private_news_chats', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '用户私有文章问答',
                'verbose_name_plural': '用户私有文章问答',
                'constraints': [models.UniqueConstraint(fields=('user', 'news'), name='unique_user_news_chat')],
            },
        ),
        migrations.AddField(
            model_name='chatgptsubscriptionconnection',
            name='oauth_mode',
            field=models.CharField(db_index=True, default='local', max_length=16),
        ),
        migrations.AddConstraint(
            model_name='chatgptsubscriptionconnection',
            constraint=models.UniqueConstraint(
                fields=('issuer', 'issued_client_id', 'subject_hash'),
                condition=models.Q(oauth_mode='website'),
                name='one_website_chatgpt_account_owner',
            ),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='oauth_mode',
            field=models.CharField(default='local', max_length=16),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='redirect_uri',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='token_auth_method',
            field=models.CharField(default='none', max_length=32),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='requested_scopes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='chatgptauthattempt',
            name='oauth_resource',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
