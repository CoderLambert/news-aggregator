"""T03 per-user task model preference: additive, no execution or provider I/O."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0062_user_ai_model_config_and_probe'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserAITaskPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_kind', models.CharField(choices=[
                    ('default', 'default'),
                    ('article_qa', 'article_qa'),
                    ('full_translation', 'full_translation'),
                    ('deep_research', 'deep_research'),
                    ('question_suggestions', 'question_suggestions'),
                ], max_length=32)),
                ('revision', models.PositiveBigIntegerField(default=1)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('model_config', models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='task_preferences', to='api.useraimodelconfig')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_task_preferences', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['task_kind']},
        ),
        migrations.AddConstraint(
            model_name='useraitaskpreference',
            constraint=models.UniqueConstraint(
                fields=('user', 'task_kind'), name='user_ai_task_preference_unique'),
        ),
    ]
