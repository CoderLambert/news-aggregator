"""Private T04 BYOK chat turn cancellation receipts, never provider secrets."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0063_user_ai_task_preference'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ArticleChatTurn',
            fields=[
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[
                    ('pending', 'pending'), ('dispatched', 'dispatched'),
                    ('cancelled', 'cancelled'), ('complete', 'complete'),
                ], default='pending', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='article_chat_turns', to='api.news')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='article_chat_turns', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
