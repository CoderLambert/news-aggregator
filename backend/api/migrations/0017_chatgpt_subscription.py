# Generated for the local ChatGPT subscription connection feature.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import api.models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0016_researchsearchresult'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatGPTOAuthClient',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('host_id', models.CharField(default=api.models.generate_chatgpt_host_id, max_length=64, unique=True)),
                ('issued_client_id', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'ChatGPT OAuth 客户端',
                'verbose_name_plural': 'ChatGPT OAuth 客户端',
            },
        ),
        migrations.CreateModel(
            name='ChatGPTSubscriptionConnection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('subject_hash', models.CharField(max_length=64)),
                ('account_name', models.CharField(blank=True, default='', max_length=255)),
                ('account_email', models.EmailField(blank=True, default='', max_length=254)),
                ('encrypted_access_token', models.TextField(blank=True, default='')),
                ('encrypted_refresh_token', models.TextField(blank=True, default='')),
                ('access_token_expires_at', models.DateTimeField(blank=True, null=True)),
                ('selected_model', models.CharField(blank=True, default='', max_length=255)),
                ('is_active', models.BooleanField(db_index=True, default=False)),
                ('needs_reauth', models.BooleanField(db_index=True, default=False)),
                ('generation', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_connections', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'ChatGPT 订阅连接',
                'verbose_name_plural': 'ChatGPT 订阅连接',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='ChatGPTAuthAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('state_hash', models.CharField(max_length=64, unique=True)),
                ('nonce_hash', models.CharField(max_length=64)),
                ('encrypted_pkce_verifier', models.TextField()),
                ('requested_client_id', models.CharField(max_length=255)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('target_connection', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='api.chatgptsubscriptionconnection')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_auth_attempts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'ChatGPT OAuth 登录尝试',
                'verbose_name_plural': 'ChatGPT OAuth 登录尝试',
            },
        ),
        migrations.CreateModel(
            name='ChatGPTArticleTranslation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_hash', models.CharField(max_length=64)),
                ('model_slug', models.CharField(max_length=255)),
                ('content', models.TextField()),
                ('completed_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translations', to='api.chatgptsubscriptionconnection')),
                ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_translations', to='api.news')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chatgpt_translations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'ChatGPT 全文翻译',
                'verbose_name_plural': 'ChatGPT 全文翻译',
            },
        ),
        migrations.AddConstraint(
            model_name='chatgptsubscriptionconnection',
            constraint=models.UniqueConstraint(fields=('user', 'subject_hash'), name='unique_chatgpt_user_subject'),
        ),
        migrations.AddConstraint(
            model_name='chatgptsubscriptionconnection',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('user',), name='one_active_chatgpt_connection_per_user'),
        ),
        migrations.AddConstraint(
            model_name='chatgptarticletranslation',
            constraint=models.UniqueConstraint(fields=('user', 'connection', 'news'), name='unique_chatgpt_news_translation'),
        ),
    ]
