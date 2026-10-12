from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0033_user_provider_credential'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprovidercredential',
            name='model_id',
            field=models.CharField(default='', max_length=128),
            preserve_default=False,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='userprovidercredential',
                    name='provider',
                    field=models.CharField(
                        choices=[
                            ('openai', 'OpenAI'),
                            ('anthropic', 'Anthropic Claude'),
                            ('deepseek', 'DeepSeek'),
                            ('gemini', 'Google Gemini'),
                            ('qwen', 'Qwen'),
                            ('glm', 'GLM / Z.AI'),
                            ('kimi', 'Kimi / Moonshot'),
                            ('mistral', 'Mistral AI'),
                            ('groq', 'Groq'),
                            ('xai', 'xAI'),
                            ('openrouter', 'OpenRouter'),
                        ],
                        max_length=16,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
